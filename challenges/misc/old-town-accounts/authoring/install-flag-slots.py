#!/usr/bin/env python3
"""Install fixed-width runtime flag slots in the live V4 master image."""
from pathlib import Path
import os
import pty
import select
import subprocess
import sys
import termios
import time

SPIKE = Path("/tmp/pdp11-spike")
BUILD = SPIKE / "build"
sys.path.insert(0, str(SPIKE))
from flagslots import SLOT_SIZE, SLOTS, slot_bytes  # noqa: E402

master, slave = pty.openpty()
attrs = termios.tcgetattr(master)
attrs[0] = attrs[1] = 0
attrs[3] &= ~(termios.ECHO | termios.ICANON)
termios.tcsetattr(master, termios.TCSANOW, attrs)
proc = subprocess.Popen(
    [str(SPIKE / "simh/BIN/pdp11"), str(BUILD / "boot-master-author.ini")],
    stdin=slave, stdout=slave, stderr=subprocess.STDOUT,
    cwd=SPIKE, preexec_fn=os.setsid)
os.close(slave)
buffer = b""
log = (BUILD / "install-flag-slots.log").open("wb")


def receive_until(needle, timeout=60):
    global buffer
    deadline = time.time() + timeout
    while needle not in buffer:
        if time.time() > deadline:
            raise TimeoutError(f"waiting for {needle!r}; tail={buffer[-200:]!r}")
        ready, _, _ = select.select([master], [], [], 1)
        if not ready:
            continue
        chunk = os.read(master, 4096)
        log.write(chunk)
        log.flush()
        buffer += chunk
    end = buffer.index(needle) + len(needle)
    result, buffer = buffer[:end], buffer[end:]
    return result


def send(data):
    if isinstance(data, str):
        data = data.encode("latin-1")
    os.write(master, data)


def command(text, timeout=60):
    send(text + "\r")
    return receive_until(b"# ", timeout)


def put_file(path, text):
    command_text = f"cat > {path}"
    send(command_text + "\r")
    receive_until((command_text + "\r").encode())
    for line in text.splitlines():
        wire = (line if line else " ").encode("latin-1") + b"\r"
        send(wire)
        receive_until(wire, 20)
    send(b"\x04")
    receive_until(b"# ", 45)


def padded(text, token):
    return text.replace(token, slot_bytes(token).decode("ascii"))


def drain(seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.25)
        if ready:
            chunk = os.read(master, 4096)
            log.write(chunk)
            log.flush()


try:
    receive_until(b"login:", 30)
    send("root\r")
    receive_until(b"Password:", 30)
    send("samhain\r")
    receive_until(b"# ", 30)

    ledger = BUILD / "ledger"
    put_file("/usr/ledger/night.rpt",
             padded((ledger / "night.rpt").read_text(), "__FLAG__"))
    put_file("/usr/clerk/mailbox",
             padded((ledger / "mailbox").read_text(),
                    "__FLAG_LEDGER_ESCAPE__"))
    put_file("/proprietor",
             padded((ledger / "proprietor").read_text(),
                    "__FLAG_PROPRIETOR__"))
    command("chown clerk /usr/clerk/mailbox")
    command("chmod 644 /usr/clerk/mailbox")
    command("chmod 644 /usr/ledger/night.rpt")
    command("chmod 400 /proprietor")
    command("sync")
    drain(3)
    command("sync")
    drain(8)
finally:
    log.close()
    try:
        proc.kill()
    except OSError:
        pass
    os.close(master)

raw = (BUILD / "master.rk").read_bytes()
for _, token in SLOTS:
    count = raw.count(slot_bytes(token))
    if count != 1:
        raise SystemExit(f"expected one padded {token} slot, found {count}")
if b"noco{" in raw.lower():
    raise SystemExit("master contains a flag literal")
print(f"installed {len(SLOTS)} unique {SLOT_SIZE}-byte flag slots")

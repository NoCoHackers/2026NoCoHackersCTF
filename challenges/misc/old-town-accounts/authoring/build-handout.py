#!/usr/bin/env python3
"""Build the stage-one forensic RK05 from the pristine stock image."""
from pathlib import Path
import os
import pty
import select
import subprocess
import termios
import time

SPIKE = Path("/tmp/pdp11-spike")
BUILD = SPIKE / "build"
SOURCE = BUILD / "handout"
SIM = SPIKE / "simh/BIN/pdp11"
IMAGE = BUILD / "handout.rk"
INI = BUILD / "boot-handout-author.ini"
LOG = BUILD / "handout-author.log"

IMAGE.write_bytes((BUILD / "stock.rk").read_bytes())

master, slave = pty.openpty()
attrs = termios.tcgetattr(master)
attrs[0] = attrs[1] = 0
attrs[3] &= ~(termios.ECHO | termios.ICANON)
termios.tcsetattr(master, termios.TCSANOW, attrs)
proc = subprocess.Popen(
    [str(SIM), str(INI)], stdin=slave, stdout=slave,
    stderr=subprocess.STDOUT, cwd=SPIKE, preexec_fn=os.setsid)
os.close(slave)
log = LOG.open("wb")
buffer = b""


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
        if not chunk:
            raise RuntimeError("emulator exited")
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


def drain(seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.25)
        if ready:
            chunk = os.read(master, 4096)
            log.write(chunk)
            log.flush()


wipe_source = """char z[512];
char b[512];
main(argc,argv)
int argc;
char **argv;
{
        int i, r, w, n, j;
        for(j=0; j<512; j++) z[j]=0;
        for(i=1; i<argc; i++) {
                r=open(argv[i],0);
                if(r<0) continue;
                w=open(argv[i],1);
                if(w<0) { close(r); continue; }
                while((n=read(r,b,512))>0) write(w,z,n);
                close(r);
                close(w);
        }
}
"""

try:
    receive_until(b"login:", 30)
    send("root\r")
    receive_until(b"# ", 30)

    command("chdir /tmp")
    put_file("/tmp/wipe.c", wipe_source)
    command("cc wipe.c", 90)
    command("mv a.out wipe")
    command("rm wipe.c")
    command("sync")

    directories = [
        "/usr/source/s1", "/usr/source/s2", "/usr/source/s3",
        "/usr/source/s4", "/usr/source/s7", "/usr/sys/conf",
        "/usr/sys/dmr", "/usr/sys/ken",
    ]
    patterns = ["[a-f]*", "[g-m]*", "[n-s]*", "[t-z]*"]
    for directory in directories:
        command("chdir " + directory)
        for pattern in patterns:
            command("/tmp/wipe " + pattern, 90)
        for pattern in patterns:
            command("rm -f " + pattern, 90)
        command("rm -f *", 90)

    command("chdir /usr/source")
    command("rmdir s1 s2 s3 s4 s7")
    command("chdir /usr/sys")
    command("rmdir conf dmr ken")
    for pattern in patterns:
        command("/tmp/wipe " + pattern, 90)
    for pattern in patterns:
        command("rm -f " + pattern, 90)
    command("rm -f *", 90)
    command("chdir /usr")
    command("rmdir source sys")
    command("rm /tmp/wipe")
    command("sync")

    command("mkdir /usr/ledger")
    command("mkdir /usr/ellis")
    files = [
        ("/etc/motd", "motd"),
        ("/usr/ledger/night.conf", "night.conf"),
        ("/usr/ledger/manual", "operator.manual"),
        ("/usr/ellis/desk.note", "desk.note"),
        ("/usr/adm/close.msg", "close.msg"),
        ("/usr/adm/watch.oct", "watch.oct"),
    ]
    for destination, name in files:
        put_file(destination, (SOURCE / name).read_text())
        command("chmod 644 " + destination)
    command("chmod 755 /usr/ledger")
    command("chmod 755 /usr/ellis")
    command("date 1030234074")

    output = b""
    for text in [
        "cat /usr/ellis/desk.note",
        "cat /usr/ledger/night.conf",
        "cat /usr/adm/close.msg",
        "grep 0317 /usr/adm/watch.oct",
        "cat /usr/ledger/manual",
    ]:
        output += command(text)
    decoded = output.decode("latin-1", "replace")
    required = [
        "OCTOBER WATCHWORD", "login role          clerk",
        "ACCOUNT 0317 OMITTED", "0317      lantern", "/dev/tty9",
        "S (summary) and D (detail)",
    ]
    missing = [item for item in required if item not in decoded]
    if missing:
        raise RuntimeError(f"build verification missing {missing!r}")

    command("sync")
    drain(3)
    command("sync")
    drain(8)
    print("handout authoring complete")
finally:
    log.close()
    try:
        proc.kill()
    except OSError:
        pass
    os.close(master)

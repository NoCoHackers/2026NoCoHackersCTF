#!/usr/bin/env python3
"""Send one lesson script and stop reading when its flag arrives."""
import re
import socket
import sys

host, port, *lines = sys.argv[1:]
with socket.create_connection((host, int(port)), timeout=10) as connection:
    connection.settimeout(150)
    connection.sendall(("\n".join(lines) + "\n").encode())
    response = b""
    while not (found := re.search(rb"noco\{[^}\r\n]+\}", response)):
        chunk = connection.recv(4096)
        if not chunk:
            raise SystemExit("solve: connection closed before the flag arrived")
        response += chunk
    print(found.group().decode())

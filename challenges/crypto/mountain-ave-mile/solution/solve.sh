#!/usr/bin/env bash
# Midnight Mountain Ave Mile - automated solve.
#
# The intended route, which this script follows exactly:
#   1. download the three surviving trace segments; rebuild node 01
#   2. recover the lost finish leaf: every value in the tree is sixteen
#      bits, so fold each candidate leaf against the certified PTS root
#      until it matches (exactly one does)
#   3. forge a finish file from the OFFICIAL COURSE GPX, exactly as a
#      player would: the organizers publish course.gpx, a Trace recorder
#      is just a GPX watch, and PTS-Cert authenticates bytes - so the
#      course file plus a trailing comment (one bib token + a four-hex
#      pad) is a perfectly certifiable "finish". Brute the pad until
#      CRC-16 hits the recovered leaf; if this bib's file has no
#      collision in that space, try the next bib - each reshuffles the
#      target
#   4. POST it to /claim; the office folds it, the root comes back, and
#      the trophy case opens
set -euo pipefail

TARGET="${TARGET:-http://localhost:8080}"

exec python3 - "$TARGET" <<'PY'
import re, sys, urllib.request

target = sys.argv[1]


def crc16(data, crc=0):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


assert crc16(b"123456789") == 0x31C3  # CRC-16/XMODEM check vector from /algorithm


def get(path):
    return urllib.request.urlopen(target + path).read()


# 1. the surviving record, out in the open
segs = [get(f"/segments/{n}.gpx") for n in ("seg_025", "seg_050", "seg_075")]
leaves = [crc16(s) for s in segs]
root = int(re.search(
    r"Certified PTS root</h3>\s*<pre><code>([0-9a-f]{4})</code>",
    get("/results").decode()).group(1), 16)
be = lambda h: h.to_bytes(2, "big")
node01 = crc16(be(leaves[0]) + be(leaves[1]))

# 2. the finish leaf is lost, but a leaf is only sixteen bits wide
target_leaf = None
for cand in range(65536):
    node23 = crc16(be(leaves[2]) + be(cand))
    if crc16(be(node01) + be(node23)) == root:
        target_leaf = cand
        break
assert target_leaf is not None, "no leaf reproduces the certified root"

# 3. forge a finish file whose CRC-16 is the lost leaf: the official
#    course GPX plus a trailing comment carrying the bib and the pad.
#    (A trailing comment after the root element is well-formed XML.)
course = get("/course.gpx")
forged = None
for bib in ("7777", "7001", "7002", "7003", "7004", "7005", "7006", "7007"):
    prefix = course + b"<!-- PTS-Trace finish claim BIB-" + bib.encode() + b" pad: "
    # hash the untouched prefix once, then only the changing digits per try
    state = crc16(prefix)
    tail = b" -->\n"
    for i in range(65536):
        if crc16(b"%04x" % i + tail, state) == target_leaf:
            forged = prefix + b"%04x" % i + tail
            claim_bib = bib
            break
    if forged:
        break

assert forged and crc16(forged) == target_leaf, "no colliding pad found"

# 4. file the claim
boundary = "nocosolve"
parts = b""
for name, value in (("bib", claim_bib), ("name", "Autosolve Ghoul"),
                    ("time_claim", "3:43.7")):
    parts += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
              f'\r\n\r\n{value}\r\n').encode()
parts += (f'--{boundary}\r\nContent-Disposition: form-data; name="gpx"; '
          f'filename="finish.gpx"\r\nContent-Type: application/gpx+xml'
          f'\r\n\r\n').encode() + forged + b"\r\n"
parts += f"--{boundary}--\r\n".encode()

req = urllib.request.Request(
    target + "/claim", data=parts,
    headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
page = urllib.request.urlopen(req).read().decode()

flag = re.search(r"noco\{[^}<]+\}", page)
if not flag:
    sys.exit("solve: no flag in claim response")
print(flag.group(0))
PY

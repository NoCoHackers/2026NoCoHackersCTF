#!/usr/bin/env python3
"""Midnight Mountain Ave Mile - timing, certification, and the award.

Every runner in the 2026 Mile wore a Poudre Tracking Systems "Trace"
recorder - a watch-style device that records continuously and emits GPX,
carved into quarter-mile segments. PTS certified the race under a
Merkle tree over the leader's four segments. Mid-race the PTS logger
stopped working: it had pushed the certified root to the results feed
and flushed three quarter segments to the archive, but the finish
segment - the one that would have named the finisher - existed only in
its memory.

So the records office has three surviving segment files, one certified
root, the official course file, and a perpetual award it cannot hand
out. The office will fold any submitted finish file into the surviving
tree; if the root comes back, that file was - as far as the office can
prove - the finish. PTS-Cert authenticates bytes, not provenance.

Stdlib only, one file, threaded http.server, unprivileged on :8080 behind
the same Traefik edge as every other web challenge. The shared theme is
grafted in from the chal-theme image, so pages are assembled here from its
header/footer partials instead of SSI (that part is base-web's job).

Routes:
  GET  /                      the incident, in brief
  GET  /results               what survived: three segments, the PTS root
  GET  /algorithm             exact construction rules + a worked example
  GET  /claim                 the claim form
  POST /claim                 submit a finish file
  GET  /segments/<slug>.gpx   the surviving trace segments - the hashed bytes
  GET  /course.gpx            the organizers' official course file
  GET  /theme/...             the shared event theme
  GET  /healthz               for the orchestrator
"""

from __future__ import annotations

import email.policy
import html
import os
import re
import sys
import xml.etree.ElementTree as ET
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import splits

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
THEME_DIR = os.environ.get("THEME_DIR", "/srv/theme")

MAX_BODY = 1_000_000     # a claim is small; generous, not infinite
MAX_GPX = 65_536         # 64 KiB of finish file is plenty of padding room

CHAL_NAME = os.environ.get("CHAL_NAME", "Midnight Mountain Ave Mile")
CHAL_CATEGORY = os.environ.get("CHAL_CATEGORY", "crypto")

# The gun clock survived even though the logger did not - it recorded a
# finish at CHAMPION_TENTHS. What nothing recorded is who crossed.
FLAG = ""


# --- the "hash" -----------------------------------------------------------------

CRC_POLY = 0x1021


def crc16(data: bytes, crc: int = 0) -> int:
    """CRC-16/XMODEM: poly 0x1021, init 0x0000, no reflection, no final xor.

    A checksum, not a hash. The timing vendor's 1998 datasheet is firm on
    this point, and Poudre Tracking Systems built PTS-Cert on it.
    """
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# The published check vector; /algorithm prints it so players can verify
# their own implementation before they trust it with a forgery.
assert crc16(b"123456789") == 0x31C3, "crc16 self-test failed"


def be(h: int) -> bytes:
    return h.to_bytes(2, "big")


# --- what survived of the certification tree ------------------------------------

ORDER = [slug for slug, _label, _place in splits.SEGMENTS]
LABEL = {slug: label for slug, label, _place in splits.SEGMENTS}
PLACE = {slug: place for slug, _label, place in splits.SEGMENTS}
SEGMENT_BYTES = splits.segments()
COURSE_BYTES = splits.course_bytes()
LEAF = {slug: crc16(SEGMENT_BYTES[slug]) for slug in ORDER}

# The first three quarter segments were flushed to the archive before the
# logger died. The finish segment was not.
SURVIVING = ORDER[:3]
FINISH_SLUG = ORDER[3]

# The lower tree is fully derivable from the surviving segments.
NODE01 = crc16(be(LEAF["seg_025"]) + be(LEAF["seg_050"]))
# ...and the root is what PTS pushed to the results feed before it died.
ROOT = crc16(be(NODE01) + be(crc16(be(LEAF["seg_075"]) + be(LEAF[FINISH_SLUG]))))


def certify(finish_leaf: int) -> int:
    """Fold a candidate finish leaf up the surviving tree.

    This is the office's entire verification: slot the submitted file in
    where the lost segment sat and see whether the PTS root comes back.
    """
    node23 = crc16(be(LEAF["seg_075"]) + be(finish_leaf))
    return crc16(be(NODE01) + be(node23))


assert certify(LEAF[FINISH_SLUG]) == ROOT, "tree self-test failed"


# --- pages ----------------------------------------------------------------------

def _read_theme(rel: str, fallback: str) -> str:
    try:
        with open(os.path.join(THEME_DIR, rel), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return fallback


HEADER = _read_theme("partials/header.html", "<header></header><div>") \
    .replace("{{CHAL_NAME}}", CHAL_NAME).replace("{{CHAL_CATEGORY}}", CHAL_CATEGORY)
FOOTER = _read_theme("partials/footer.html", "</div><footer></footer>")

THEME_FILES = {
    "theme.bundle.css": ("text/css; charset=utf-8", _read_theme("theme.bundle.css", "")),
    "favicon.svg": ("image/svg+xml", _read_theme("favicon.svg", "")),
}


def page(title: str, body: str) -> bytes:
    head = (
        "<!doctype html>\n<html lang=\"en\" data-theme=\"dark\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title} &middot; NoCo Hackers CTF 2026</title>\n"
        "<link rel=\"stylesheet\" href=\"/theme/theme.bundle.css\">\n"
        "<link rel=\"icon\" href=\"/theme/favicon.svg\" type=\"image/svg+xml\">\n"
        "</head>\n<body>\n"
    )
    return (head + HEADER + body + FOOTER + "</body>\n</html>\n").encode()


def _h(value: int) -> str:
    return "%04x" % value


def _diagram() -> str:
    l0, l1, l2 = (_h(LEAF[s]) for s in SURVIVING)
    return f"""
            PTS certified root  
                 {ROOT:04x}
             /                  \\
      node 01              node 23 
    {NODE01:04x}              lost
       /      \\            /      \\
  {l0}        {l1}         {l2}     lost
   0.25 mi   0.50 mi   0.75 mi   FINISH
"""


def index_page() -> bytes:
    body = f"""
<div class="noco-stack">
  <p>Every Halloween at midnight, Old Town empties out; except for
    Mountain Avenue, where the founding ghosts run the Mile. This year,
    for the first time, every runner wore a Poudre Tracking Systems
    <b>Trace</b> recorder: a small wristband, featuring continuous GPX
    recording, with periodic uploads via 5G in quarter-mile segments and 
    certified live in real time using a Merkle tree. </p>

  <p>At the end of the race, the PTS backend glitched. It had already
    pushed the certified root to the results feed and flushed three
    quarter segments to the archive. The last segment, which would 
    have named the winner, existed only in the logger's memory. Due to 
    a miscommunication, most participants, including the lead pack, left 
    without returning their wristband (ghosts don't care for the after party).
    The race director is now asking participants to upload the GPX files 
    on their wristbands so they can give the winner their prize.</p>

  <div class="noco-grid">
    <div class="noco-card">
      <h3>What survived</h3>
      <p>Three quarter-mile trace segments, the certified root, and the
        <a href="/course.gpx">official course file</a>.</p>
      <p><a href="/results">View the surviving record</a></p>
    </div>
    <div class="noco-card">
      <h3>The algorithm</h3>
      <p>Exactly how the certification tree is built, with a worked
        example you can check by hand.</p>
      <p><a href="/algorithm">Read the construction rules</a></p>
    </div>
    <div class="noco-card">
      <h3>Claim the award</h3>
      <p>The office will accept the file with a matching root 
      as the finish. Reproduce the certified root and the award 
      is yours.</p>
      <p><a href="/claim">Submit a finish file</a></p>
    </div>
  </div>

</div>"""
    return page(CHAL_NAME, body)


def results_page() -> bytes:
    cards = []
    for slug in SURVIVING:
        cards.append(f"""
    <div class="noco-card">
      <h3>{LABEL[slug]} &mdash; {PLACE[slug]}</h3>
      <p>Leaf hash: <code>{_h(LEAF[slug])}</code></p>
      <p><a href="/segments/{slug}.gpx">{slug}.gpx</a> ({len(SEGMENT_BYTES[slug])} bytes)</p>
    </div>""")
    body = f"""
<div class="noco-stack">
  <p>The whole certified record the office has left. Three trace
    segments, one root, and a hole where the finish used to be.</p>

  <div class="noco-card">
    <h3>Certified PTS root</h3>
    <pre><code>{_h(ROOT)}</code></pre>
  </div>

  <div class="noco-card">
    <h3>The certification tree</h3>
    <pre><code>{_diagram()}</code></pre>
    <p>Node 01 can be rebuilt from the surviving segments &mdash;
      download them and check the office's arithmetic. Node 23 and the
      finish leaf went down with the logger. PTS has only the root.</p>
  </div>

  <div class="noco-grid">
    {''.join(cards)}
  </div>

  <div class="noco-card">
    <h3>The official course</h3>
    <p>One mile east along Mountain Avenue, downhill from the City Park
      end into Old Town, as laid out by the organizers:
      <a href="/course.gpx">course.gpx</a>. The recorders follow it;
      so, presumably, did the finisher.</p>
  </div>

  <div class="noco-note">
    <p>The surviving segments read recorder <b>BIB
      {splits.CHAMPION_BIB}</b> &mdash; {splits.CHAMPION_NAME} &mdash;
      at every quarter: a 2:48.7 three-quarter split, negative-splitting
      into the dark. Whether he held on, and who crossed the line at
      {splits.CHAMPION_TIME}, is exactly what the lost segment would
      have proved.</p>
  </div>
</div>"""
    return page("The Surviving Record", body)


def algorithm_page() -> bytes:
    # A fully worked fold with the real numbers, so the construction can
    # be checked by hand before anyone has to trust - or attack - it.
    example = f"""
leaf 0.25 = CRC16(seg_025.gpx) = {_h(LEAF['seg_025'])}
leaf 0.50 = CRC16(seg_050.gpx) = {_h(LEAF['seg_050'])}

node 01  = CRC16( be({_h(LEAF['seg_025'])}) || be({_h(LEAF['seg_050'])}) )
         = {_h(NODE01)}

...which matches node 01 on the results page. QED, says the office."""
    body = f"""
<div class="noco-stack">
  <div class="noco-card">
    <h3>Leaf hashes</h3>
    <p>A leaf is the CRC-16 of a segment file's bytes, exactly as
      downloaded. One file in, two bytes out &mdash; every value in this
      tree is sixteen bits.</p>
    <pre><code>leaf = CRC16( file bytes )</code></pre>
  </div>

  <div class="noco-card">
    <h3>The checksum</h3>
    <p>CRC-16/XMODEM, the vendor standard since before the office kept
      records:</p>
    <pre><code>polynomial 0x1021    init 0x0000
no reflection in or out    no final xor
check: CRC16(b"123456789") = 31c3</code></pre>
    <p>That check line is a test vector: run those nine bytes through your
      own implementation and compare before you certify anything with it.</p>
  </div>

  <div class="noco-card">
    <h3>Internal nodes</h3>
    <p>Each parent checksums its two children, each hashed value written as
      two bytes, big-endian, left child first:</p>
    <pre><code>parent = CRC16( be(left) || be(right) )</code></pre>
    <p>Worked example, the lower-left corner of the tree:</p>
    <pre><code>{example}</code></pre>
  </div>

  <div class="noco-card">
    <h3>What the office can rebuild</h3>
    <p>PTS kept only the root, so this is the fold the office performs on
      whatever finish file you submit &mdash; your file slides into the
      slot the lost segment left:</p>
    <pre><code>your leaf = CRC16( your finish file )
node 23   = CRC16( be(leaf_075) || be(your leaf) )
PTS root  = CRC16( be(node 01) || be(node 23) )</code></pre>
    <p>Match the certified root and your finish is, as far as the office
      can prove, the finish.</p>
  </div>

  <div class="noco-note">
    <p>Certification covers bytes, not meaning. The Trace recorders emit
      ordinary GPX &mdash; comments, whitespace, vendor extensions and
      all &mdash; and the fold neither knows nor cares. PTS-Cert
      authenticates bytes, not provenance.</p>
  </div>
</div>"""
    return page("The Certification Algorithm", body)


CLAIM_RULES = f"""
<ol>
  <li>Your finish file must be well-formed GPX (root element
      <code>&lt;gpx&gt;</code>), 64&nbsp;KiB or smaller.</li>
  <li>Your claimed time (m:ss.t) must match the gun clock:
      <b>{splits.CHAMPION_TIME}</b>. The office knows <i>when</i> the
      finisher crossed; you are claiming to be the finisher, not beating
      one.</li>
  <li>The office folds your file into the surviving tree and compares
      against the certified PTS root. Match, and your finish is
      certified.</li>
</ol>"""


def claim_form_page() -> bytes:
    body = f"""
<div class="noco-stack">
  <p>The perpetual award waits for whoever's finish file certifies under
    the PTS root. The office kept the root; you bring the file.</p>
  <div class="noco-card"><h3>The rules</h3>{CLAIM_RULES}</div>
  <form method="post" action="/claim" enctype="multipart/form-data" class="noco-stack">
    <label>Your bib<br><input type="text" name="bib" size="10" placeholder="4242"></label><br>
    <label>Your name<br><input type="text" name="name" size="30" placeholder="Cadaver Counterfeit"></label><br>
    <label>Claimed time (m:ss.t)<br><input type="text" name="time_claim" size="10" placeholder="3:43.7"></label><br>
    <label>Your finish file (GPX)<br><input type="file" name="gpx"></label><br>
    <button type="submit">Submit the file</button>
  </form>
  <div class="noco-note"><p>Bib and name go on the trophy plaque; the
    certification never saw them. PTS-Cert covers bytes, not identity -
    which is the office's whole problem. Denials explain themselves: the
    office returns your leaf hash and the root it folded to, so you can
    see where your paperwork went wrong. No refunds on the filing fee.
    There is no filing fee.</p></div>
</div>"""
    return page("Claim the Award", body)


def _outcome_page(ok: bool, heading: str, detail_html: str) -> bytes:
    if ok:
        cls, note = "noco-card", ""
    else:
        cls, note = "noco-note", "<p><a href=\"/claim\">Fix the paperwork and file again.</a></p>"
    body = f"""
<div class="noco-stack">
  <div class="{cls}"><h3>{heading}</h3>{detail_html}</div>
  {note}
</div>"""
    return page("Claim Outcome", body)


# --- claim handling ---------------------------------------------------------------

TIME_RE = re.compile(r"^(\d{1,2}):([0-5][0-9])(\.\d)?$")
BIB_RE = re.compile(r"^[0-9]{1,5}$")


def parse_multipart(ctype: str, body: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    """Split a multipart/form-data body into text fields and file bytes.

    The file parts are the exact bytes the client sent - certification
    covers bytes, so nothing is allowed to re-encode them on the way in.
    """
    msg = BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
    fields: dict[str, str] = {}
    files: dict[str, bytes] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        if part.get_filename():
            files[name] = payload
        else:
            fields[name] = payload.decode("utf-8", "replace").strip()
    return fields, files


def _tenths(text: str) -> int | None:
    """Parse m:ss.t into integer tenths (the gun clock's resolution)."""
    m = TIME_RE.match(text)
    if not m:
        return None
    whole = int(m.group(1)) * 60 + int(m.group(2))
    frac = int(m.group(3)[1:]) if m.group(3) else 0
    return whole * 10 + frac


def judge_claim(fields: dict[str, str], files: dict[str, bytes]) -> tuple[bool, str]:
    """Every check, collected gently; the office itemizes its denials."""
    problems: list[str] = []
    bib = fields.get("bib", "")
    name = fields.get("name", "")
    time_claim = fields.get("time_claim", "")
    gpx = files.get("gpx")

    if not gpx:
        return False, "<li>No finish file attached.</li>"
    if len(gpx) > MAX_GPX:
        return False, "<li>Finish file exceeds 64 KiB.</li>"

    if not BIB_RE.match(bib):
        problems.append("Bib must be 1-5 digits.")
    if not name or len(name) > 40:
        problems.append("A name is required (40 characters or fewer).")
    if not time_claim:
        problems.append("No claimed time.")

    try:
        root_el = ET.fromstring(gpx)
    except (ET.ParseError, ValueError):
        problems.append("Finish file is not well-formed XML.")
    else:
        local = root_el.tag.rsplit("}", 1)[-1].lower()
        if local != "gpx":
            problems.append("Finish file must be a GPX document (root element <gpx>).")

    tenths = _tenths(time_claim) if time_claim else None
    if tenths is None:
        if time_claim:
            problems.append("Time must look like m:ss.t (e.g. 3:43.7).")
    elif tenths != splits.CHAMPION_TENTHS:
        problems.append(
            f"The gun clock recorded the finish at {splits.CHAMPION_TIME}. "
            f"You are claiming to be the finisher, not beating one - claim "
            f"the finisher's time.")

    if problems:
        return False, "<li>" + "</li><li>".join(problems) + "</li>"

    # The heart of it: fold this file in where the lost segment sat.
    leaf = crc16(gpx)
    got = certify(leaf)
    if got != ROOT:
        detail = ("<li>Finish file does not reproduce the certified PTS "
                  f"root (folded to {got:04x}, certified {ROOT:04x}).</li>"
                  + _deny_note(leaf, got))
        return False, detail

    # Certified. The trophy case creaks open.
    detail = f"""
<p>The office has folded your file into the surviving tree and the
certified root came back: {ROOT:04x}. As far as anyone can prove, this
was the finish.</p>
<p>{html.escape(name)} (BIB {html.escape(bib)}), {html.escape(time_claim)}.
The perpetual award is yours:</p>
<pre><code>{html.escape(FLAG)}</code></pre>
<p>Hang it somewhere the sun doesn't reach. Congratulations &mdash; the
Headless Harrier will want a rematch next Halloween.</p>"""
    return True, detail


def _deny_note(leaf: int | None, folded: int | None) -> str:
    """The office shows its arithmetic; paperwork should be debuggable."""
    rows = f"\ncertified PTS root: {ROOT:04x}"
    if leaf is not None:
        rows += f"\nYour leaf hash: {leaf:04x}"
    if folded is not None:
        rows += f"\nYour file folds to: {folded:04x}"
    return f"<pre><code>{rows}</code></pre>"


# --- http plumbing --------------------------------------------------------------

SECURITY_HEADERS = (
    ("Content-Security-Policy",
     "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
)


class Handler(BaseHTTPRequestHandler):
    # Hide the Python version; the office does not discuss its fixtures.
    server_version = "MAM-Timing/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8",
              extra: tuple = ()) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, val in SECURITY_HEADERS:
            self.send_header(key, val)
        for key, val in extra:
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        body = page("Not Found", """
<div class="noco-stack">
  <p>Nothing certified exists at this address. The office suggests the
    <a href="/">front desk</a>.</p>
</div>""")
        self._send(404, body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, b"ok\n", "text/plain; charset=utf-8")
        elif path in ("/", "/index.html"):
            self._send(200, index_page())
        elif path == "/results":
            self._send(200, results_page())
        elif path == "/algorithm":
            self._send(200, algorithm_page())
        elif path == "/claim":
            self._send(200, claim_form_page())
        elif path == "/course.gpx":
            self._send(200, COURSE_BYTES, "application/gpx+xml",
                       extra=(("Cache-Control", "public, max-age=604800"),))
        elif path.startswith("/segments/"):
            slug = path[len("/segments/"):].removesuffix(".gpx")
            if slug in SURVIVING:
                self._send(200, SEGMENT_BYTES[slug], "application/gpx+xml",
                           extra=(("Cache-Control", "no-store"),))
            elif slug == FINISH_SLUG:
                # The file everyone wants is the one that burned.
                self._send(410, page("Gone", """
<div class="noco-stack">
  <p>That segment never made it off the logger. The office has only the
    <a href="/results">certified root</a>.</p>
</div>"""))
            else:
                self._not_found()
        elif path.startswith("/theme/"):
            name = path[len("/theme/"):]
            if name in THEME_FILES:
                ctype, content = THEME_FILES[name]
                self._send(200, content.encode(), ctype,
                           extra=(("Cache-Control", "public, max-age=604800"),))
            else:
                self._not_found()
        else:
            self._not_found()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/claim":
            self._not_found()
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self._send(415, page("Wrong Window", """
<div class="noco-stack"><p>Claims are filed by the form at
<a href="/claim">/claim</a> (multipart/form-data).</p></div>"""))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = MAX_BODY + 1
        if length > MAX_BODY:
            self.close_connection = True
            self._send(413, page("Too Heavy", """
<div class="noco-stack"><p>That claim weighs more than a megabyte. The
office declines to lift it.</p></div>"""))
            return
        body = self.rfile.read(length)
        fields, files = parse_multipart(ctype, body)
        ok, detail = judge_claim(fields, files)
        heading = "Finish certified." if ok else "Claim returned."
        self._send(200, _outcome_page(ok, heading,
                                      ("<ul>%s</ul>" % detail) if not ok else detail))


def main() -> None:
    global FLAG
    FLAG = os.environ.get("FLAG", "")
    if not FLAG:
        sys.exit("FATAL: FLAG is not set - the trophy case is locked. Set the "
                 "FLAG environment variable (compose and make dev do this).")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"mam: timing office open on {HOST}:{PORT}, certified PTS root {ROOT:04x}",
          flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""A tiny registry promotion gate with a very deliberate trust-boundary mistake."""
import hashlib
import html
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
THEME = Path("/srv/theme")
TEMPLATE = (HERE / "index.html").read_text()
DIGEST = "sha256:" + hashlib.sha256(b"old-town/lantern-cam:pr-47").hexdigest()
PROVENANCE = {
    "digest": DIGEST,
    "source": {"branch": "feature/night-vision"},
    "result": "passed",
}
DEFAULT_DESCRIPTION = "Night watch camera build for the Old Town lantern route."


def verify(description):
    # The CI record is trusted; the listing description is not. This importer
    # mistakenly treats JSON-looking lines from both sources as equal records.
    stream = json.dumps(PROVENANCE, separators=(",", ":")) + "\n" + description + "\n"
    records = subprocess.run(
        ["jq", "-cR", 'fromjson? | select(type == "object")'],
        input=stream, text=True, capture_output=True, check=True, timeout=2,
    ).stdout
    decision = subprocess.run(
        ["jq", "-sc", "--arg", "digest", DIGEST,
         'any(.[]; .digest == $digest and .source.branch == "main" and .result == "passed")'],
        input=records, text=True, capture_output=True, check=True, timeout=2,
    ).stdout.strip()
    return decision == "true", len(records.splitlines())


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type="text/html; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", "default-src 'self'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def page(self, description=DEFAULT_DESCRIPTION, approved=None, count=0):
        state, state_class = "Waiting", "run-badge--waiting"
        step_class, step_icon, step_message = "step-pending", "—", "Awaiting manual run"
        status = '<p class="job-idle">— Promotion check has not run.</p>'
        audit = "<p>No verifier output yet.</p>"
        if approved is not None:
            audit = (f"<p>jq: {count} JSON record(s) parsed.</p>"
                     "<p>Policy: matching digest, passing result, branch <code>main</code>.</p>")
            if approved:
                state, state_class = "Passed", "run-badge--passed"
                step_class, step_icon, step_message = "step-ok", "✓", "Promotion approved"
                status = ('<p class="job-ok">✓ Promotion approved.</p><p class="noco-flag">'
                          + html.escape(os.environ["FLAG"]) + "</p>")
            else:
                state, state_class = "Failed", "run-badge--failed"
                step_class, step_icon = "step-failed", "×"
                step_message = "No passing main-branch build for this digest"
                status = '<p class="job-error">× Promotion denied: no passing main-branch build for this digest.</p>'
        page = TEMPLATE.replace("%%DIGEST%%", html.escape(DIGEST))
        page = page.replace("%%PROVENANCE%%", html.escape(json.dumps(PROVENANCE, indent=2)))
        page = page.replace("%%DESCRIPTION%%", html.escape(description))
        page = page.replace("%%STATE_CLASS%%", state_class).replace("%%RUN_STATE%%", state)
        page = page.replace("%%STEP_CLASS%%", step_class).replace("%%STEP_ICON%%", step_icon)
        page = page.replace("%%STEP_MESSAGE%%", step_message)
        page = page.replace("%%STATUS%%", status).replace("%%AUDIT%%", audit)
        self.reply(200, page)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.page()
        elif path == "/healthz":
            self.reply(200, "ok\n", "text/plain; charset=utf-8")
        elif path == "/registry.css":
            self.reply(200, (HERE / "registry.css").read_bytes(), "text/css")
        elif path in ("/theme/theme.bundle.css", "/theme/favicon.svg"):
            name = path.rsplit("/", 1)[-1]
            kind = "text/css" if name.endswith(".css") else "image/svg+xml"
            self.reply(200, (THEME / name).read_bytes(), kind)
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/promote":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        if not 0 < size <= 8192:
            self.send_error(413, "Description is too long or missing")
            return
        fields = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
        description = fields.get("description", [""])[0]
        if len(description) > 4096:
            self.send_error(413, "Description is too long")
            return
        approved, count = verify(description)
        self.page(description, approved, count)


if __name__ == "__main__":
    if not re.fullmatch(r"noco\{[^}]+\}", os.environ.get("FLAG", "")):
        raise SystemExit("FATAL: set FLAG to a noco{...} value before starting the registry")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

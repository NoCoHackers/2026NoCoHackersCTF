#!/usr/bin/env python3
"""Review uploaded builds, then run approved ones in a syscall-only jail."""
import hashlib
import html
import json
import os
import re
import resource
import subprocess
import tempfile
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ARTIFACT = Path("/srv/artifact/cache-de-spectre")
THEME = Path("/srv/theme")
TEMPLATE = (HERE / "index.html").read_text()
BINARY = ARTIFACT.read_bytes()
DIGEST = "sha256:" + hashlib.sha256(BINARY).hexdigest()
PROVENANCE = {"digest": DIGEST, "source": {"branch": "feature/poudre"}, "result": "passed"}
DEFAULT_METADATA = json.dumps({"description": "Cache de Spectre: nightly preview build"})
MAX_REQUEST = 128 * 1024


def verify(metadata, uploaded_digest):
    extracted = subprocess.run(
        ["jq", "-er", 'if type == "object" and (.description | type) == "string" then .description else empty end'],
        input=metadata, text=True, capture_output=True, timeout=2,
    )
    if extracted.returncode != 0:
        return False, 0, "Expected a JSON object with a description string."
    description = extracted.stdout.rstrip("\n")
    if not description.startswith("Cache de Spectre: ") or len(description) <= len("Cache de Spectre: "):
        return False, 0, 'Description must start with "Cache de Spectre: ".'

    # jq -r above decodes JSON escapes. The importer below mistakes any JSON
    # line in the untrusted description for a second CI provenance record.
    stream = json.dumps(PROVENANCE, separators=(",", ":")) + "\n" + description + "\n"
    records = subprocess.run(
        ["jq", "-cR", 'fromjson? | select(type == "object")'],
        input=stream, text=True, capture_output=True, check=True, timeout=2,
    ).stdout
    decision = subprocess.run(
        ["jq", "-s", "--arg", "digest", uploaded_digest,
         'any(.[]; .digest == $digest and .source.branch == "main" and .result == "passed")'],
        input=records, text=True, capture_output=True, check=True, timeout=2,
    ).stdout.strip()
    return decision == "true", len(records.splitlines()), None


def limit_job():
    resource.setrlimit(resource.RLIMIT_AS, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))


def run_job(uploaded):
    # /tmp is noexec. Pass the ELF in a memfd to a separate child with no
    # environment, one secret on stdin, and a seccomp syscall allowlist.
    fd = os.memfd_create("candidate", 0)
    try:
        with os.fdopen(os.dup(fd), "wb") as candidate:
            candidate.write(uploaded)
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            output = Path(directory) / "output"
            try:
                with output.open("wb") as stdout:
                    result = subprocess.run(
                        ["/usr/local/bin/noco-jail", str(fd)],
                        input=(os.environ["NOCO_FLAG_EXEC"] + "\n").encode(),
                        stdout=stdout, stderr=subprocess.DEVNULL,
                        cwd=directory, env={}, timeout=3, preexec_fn=limit_job,
                        pass_fds=(fd,),
                    )
            except subprocess.TimeoutExpired:
                return "Job timed out."
            text = output.read_bytes().decode("utf-8", errors="replace")
            if result.returncode != 0:
                text += "\nJob exited without completing."
            return text or "Job produced no output."
    finally:
        os.close(fd)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type="text/html; charset=utf-8", filename=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", "default-src 'self'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def page(self, metadata=DEFAULT_METADATA, status=None, count=None, uploaded_digest=None, job_output=""):
        digest_line = ("<p>Uploaded SHA-256: <code>" + html.escape(uploaded_digest) + "</code></p>"
                       if uploaded_digest else "")
        if status is None:
            result = '<p class="muted">No review has run yet.</p>'
            audit = "<p>No verifier output yet.</p>"
        elif status == "approved":
            result = ('<p class="success">Promotion approved.</p><p class="noco-flag">'
                      + html.escape(os.environ["FLAG"]) + "</p>"
                      '<h3>Release job</h3><pre><code>' + html.escape(job_output) + "</code></pre>")
            audit = f"<p>jq/jsonl: {count} record(s) parsed. Policy passed.</p>"
        else:
            result = '<p class="error">' + html.escape(status) + "</p>"
            audit = (f"<p>jq/jsonl: {count} record(s) parsed. Policy failed.</p>" if count is not None
                     else "<p>Verifier did not run.</p>")
        page = TEMPLATE.replace("%%DIGEST%%", html.escape(DIGEST))
        page = page.replace("%%PROVENANCE%%", html.escape(json.dumps(PROVENANCE, indent=2)))
        page = page.replace("%%METADATA%%", html.escape(metadata))
        page = page.replace("%%STATUS%%", digest_line + result).replace("%%AUDIT%%", audit)
        self.reply(200, page)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.page()
        elif path == "/healthz":
            self.reply(200, "ok\n", "text/plain; charset=utf-8")
        elif path == "/artifact/cache-de-spectre":
            self.reply(200, BINARY, "application/octet-stream", "cache-de-spectre")
        elif path == "/registry.css":
            self.reply(200, (HERE / "registry.css").read_bytes(), "text/css")
        elif path in ("/theme/theme.bundle.css", "/theme/favicon.svg"):
            name = path.rsplit("/", 1)[-1]
            kind = "text/css" if name.endswith(".css") else "image/svg+xml"
            self.reply(200, (THEME / name).read_bytes(), kind)
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/review":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        content_type = self.headers.get("Content-Type", "")
        if not 0 < size <= MAX_REQUEST or not content_type.startswith("multipart/form-data;"):
            self.send_error(400, "Upload a small binary and metadata as multipart form data")
            return
        raw = (b"Content-Type: " + content_type.encode("ascii", errors="ignore")
               + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.rfile.read(size))
        message = BytesParser(policy=policy.default).parsebytes(raw)
        fields = {}
        if message.is_multipart():
            for part in message.iter_parts():
                if part.get_content_disposition() == "form-data":
                    name = part.get_param("name", header="content-disposition")
                    if name in ("binary", "metadata") and name not in fields:
                        fields[name] = part.get_payload(decode=True)
        if not isinstance(fields.get("binary"), bytes) or not isinstance(fields.get("metadata"), bytes):
            self.send_error(400, "Both binary and metadata fields are required")
            return
        try:
            metadata = fields["metadata"].decode("utf-8")
        except UnicodeDecodeError:
            self.send_error(400, "Metadata must be UTF-8 JSON")
            return
        uploaded = fields["binary"]
        if not uploaded.startswith(b"\x7fELF") or len(uploaded) > 64 * 1024:
            self.page(metadata, "Artifact rejected: upload a small ELF executable.")
            return
        uploaded_digest = "sha256:" + hashlib.sha256(uploaded).hexdigest()
        approved, count, error = verify(metadata, uploaded_digest)
        self.page(metadata, "approved" if approved else error or
                  "Promotion denied: no passing main-branch build for this digest.", count,
                  uploaded_digest, run_job(uploaded) if approved else "")


if __name__ == "__main__":
    if not re.fullmatch(r"noco\{[^}]+\}", os.environ.get("FLAG", "")) or not re.fullmatch(
            r"noco\{[^}]+\}", os.environ.get("NOCO_FLAG_EXEC", "")):
        raise SystemExit("FATAL: set FLAG and NOCO_FLAG_EXEC to noco{...} values before starting")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

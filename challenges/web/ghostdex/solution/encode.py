#!/usr/bin/env python3
"""Bake the invisible flag payload into src/index.html.

The flag is hidden one character per word: each flag character becomes a
Unicode tag character, U+E0000 + ord(c), and is inserted right after a word
of visible body text. The tag block mirrors ASCII with a simple offset and
its characters render zero-width, so the page reads normally while carrying
the flag -- a player who hexdumps the source or copies the text out and
subtracts 0xE0000 from every tag codepoint recovers it.

Idempotent: existing tag characters are stripped before re-inserting, so re-run
this after any copy edit. The <body> needs at least as many words as the flag
has characters.

    python3 solution/encode.py            # bake the flag from challenge.yml
    python3 solution/encode.py --decode  # print the payload currently baked in

Standard library plus PyYAML, matching the repo's tooling style.
"""

import re
import sys
from pathlib import Path

import yaml

TAG_BASE = 0xE0000          # tag block start; U+E0000 + ord(c) mirrors ASCII
TAG_END = 0xE007F

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "src" / "index.html"
MANIFEST = ROOT / "challenge.yml"

# Anything that looks like a tag -- elements, <!doctype>, <!-- SSI --> -- is
# left untouched; payload characters only land in visible text.
TAG_RE = re.compile(r"<[^>]*>")
WORD_RE = re.compile(r"\S+")
BODY_RE = re.compile(r"<body[^>]*>")


def strip_payload(text):
    return "".join(c for c in text if not TAG_BASE <= ord(c) <= TAG_END)


def decode_payload(text):
    return "".join(chr(ord(c) - TAG_BASE) for c in text
                   if TAG_BASE <= ord(c) <= TAG_END)


def inject(html, chars):
    def splice(text):
        return WORD_RE.sub(lambda m: m.group(0) + next(chars, ""), text)

    out, pos = [], 0
    for m in TAG_RE.finditer(html):
        out.append(splice(html[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(splice(html[pos:]))
    return "".join(out)


def main():
    if "--decode" in sys.argv[1:]:
        payload = decode_payload(PAGE.read_text(encoding="utf-8"))
        if not payload:
            sys.exit(f"FATAL: no tag-block payload found in {PAGE}")
        print(payload)
        return

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    flag = manifest["flags"][0]

    html = strip_payload(PAGE.read_text(encoding="utf-8"))
    body = BODY_RE.search(html)
    if not body:
        sys.exit(f"FATAL: {PAGE} has no <body> to hide the payload in")

    # Only the body carries the payload; the <title> stays clean.
    chars = iter(chr(TAG_BASE + ord(c)) for c in flag)
    html = html[:body.end()] + inject(html[body.end():], chars)

    placed = decode_payload(html)
    if placed != flag:
        words = len(WORD_RE.findall(strip_payload(html[body.end():])))
        sys.exit(f"FATAL: body has {words} words but the flag is "
                 f"{len(flag)} characters; add copy or shorten the flag")

    PAGE.write_text(html, encoding="utf-8")
    print(f"baked {len(flag)} tag characters into {PAGE}")


if __name__ == "__main__":
    main()

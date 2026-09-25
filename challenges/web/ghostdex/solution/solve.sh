#!/usr/bin/env bash
# Automated solution. CI runs this against a freshly built container on every
# pull request; if it stops printing the flag, the build goes red.
#
# The page hides its flag as Unicode tag characters (U+E0000 + ord), one after
# each of the first 38 words of body text. Extract the tag block in document
# order and subtract the offset.
#
# Contract:
#   - $TARGET is the base URL (web) or "host port" (tcp), injected by CI
#   - print the flag to stdout, nothing else on stdout
#   - exit 0 on success, non-zero on failure
set -euo pipefail

TARGET="${TARGET:-http://localhost:8080}"

flag=$(curl -fsS "$TARGET/" | python3 -c '
import sys

text = sys.stdin.buffer.read().decode("utf-8", "replace")
print("".join(chr(ord(c) - 0xE0000) for c in text
             if 0xE0000 <= ord(c) <= 0xE007F))
')

if [[ "$flag" != noco{*} ]]; then
  echo "solve: no hidden payload found at $TARGET" >&2
  exit 1
fi

echo "$flag"

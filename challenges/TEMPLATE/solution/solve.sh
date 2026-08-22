#!/usr/bin/env bash
# Automated solution. CI runs this against a freshly built container on every
# pull request; if it stops printing the flag, the build goes red.
#
# Contract:
#   - $TARGET is the base URL (web) or "host port" (tcp), injected by CI
#   - print the flag to stdout, nothing else on stdout
#   - exit 0 on success, non-zero on failure
#   - no interactive prompts, no sleeps longer than a few seconds
set -euo pipefail

TARGET="${TARGET:-http://localhost:8080}"

flag=$(curl -fsS "$TARGET/" | grep -oE 'noco\{[^}]+\}' | head -1)

if [[ -z "$flag" ]]; then
  echo "solve: no flag found at $TARGET" >&2
  exit 1
fi

echo "$flag"

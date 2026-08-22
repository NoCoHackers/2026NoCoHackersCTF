#!/usr/bin/env bash
# Haunted Brewery - automated solve.
# recon: robots.txt -> disallowed directory -> manifest named on that page.
set -euo pipefail

TARGET="${TARGET:-http://localhost:8080}"

dir=$(curl -fsS "$TARGET/robots.txt" | awk '/^Disallow:/ {print $2; exit}')
[[ -n "$dir" ]] || { echo "solve: no Disallow entry in robots.txt" >&2; exit 1; }

manifest=$(curl -fsS "$TARGET$dir" | grep -oE '[a-z-]+\.json' | head -1)
[[ -n "$manifest" ]] || { echo "solve: no manifest named on $dir" >&2; exit 1; }

flag=$(curl -fsS "$TARGET$dir$manifest" | grep -oE 'noco\{[^}]+\}' | head -1)
[[ -n "$flag" ]] || { echo "solve: no flag in $dir$manifest" >&2; exit 1; }

echo "$flag"

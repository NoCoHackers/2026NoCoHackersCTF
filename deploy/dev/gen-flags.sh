#!/usr/bin/env sh
# Write the gitignored dev runtime environment from the challenge manifests.
set -eu
cd "$(dirname "$0")/../.."
OUT=deploy/dev/flags.env
tmp=$OUT.tmp
trap 'rm -f "$tmp"' EXIT
python3 tools/chalbundle.py env > "$tmp"
chmod 600 "$tmp"
mv "$tmp" "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") flags)"

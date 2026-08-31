#!/usr/bin/env sh
# Write deploy/dev/flags.env from every scoreboard manifest. In dev the flags
# come straight from challenge.yml files; production still uses sops/age.
set -eu
cd "$(dirname "$0")/../.."
OUT=deploy/dev/flags.env
python3 tools/chalbundle.py env > "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") flags)"

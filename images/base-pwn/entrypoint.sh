#!/bin/sh
# NoCo base-pwn entrypoint: place the flag, render the banner, then hand off to
# socat which forks one process per incoming connection.
set -eu

if [ -z "${FLAG:-}" ]; then
  echo "noco: FATAL - FLAG is empty." >&2; exit 1
fi
case "$FLAG" in
  noco\{*\}) : ;;
  *) echo "noco: FATAL - FLAG does not match noco{...}" >&2; exit 1 ;;
esac

if ! ( : > /flag/.writetest ) 2>/dev/null; then
  echo "noco: FATAL - /flag is not writable." >&2
  echo "noco:   run with --tmpfs /flag (compose: tmpfs: [/flag])" >&2
  exit 1
fi
rm -f /flag/.writetest

# Root-owned, world-readable. The challenge runs as `ctf` and can read these
# but not rewrite them. /flag/flag.txt remains the primary compatibility path;
# bundle entries also get stable lowercase names such as /flag/uart-debug.txt.
printf '%s\n' "$FLAG" > /flag/flag.txt
FLAGS_FILE=/tmp/noco-flags.$$
env | grep -E '^NOCO_FLAG_[A-Z0-9_]+=' > "$FLAGS_FILE" || :
while IFS= read -r pair; do
  variable=${pair%%=*}
  value=${pair#*=}
  case "$value" in
    noco\{*\}) : ;;
    *) echo "noco: FATAL - named flag does not match noco{...}" >&2; exit 1 ;;
  esac
  entry_id=$(printf '%s' "${variable#NOCO_FLAG_}" | tr 'A-Z_' 'a-z-')
  printf '%s\n' "$value" > "/flag/${entry_id}.txt"
done < "$FLAGS_FILE"
rm -f "$FLAGS_FILE"
chmod 644 /flag/*.txt

if [ ! -x "$CHAL_BIN" ]; then
  echo "noco: FATAL - CHAL_BIN '$CHAL_BIN' is missing or not executable." >&2
  exit 1
fi

# Pad the name to the banner's fixed 40-column field so the box border stays
# aligned whatever the challenge is called; %-40.40s also truncates a name
# that would otherwise push the border off the edge.
NAME_FIELD=$(printf '%-40.40s' "$CHAL_NAME")
sed "s|{{CHAL_NAME}}|${NAME_FIELD}|g" /srv/banner.txt > /tmp/banner

echo "noco: '${CHAL_NAME}' serving ${CHAL_BIN} on :1337 (fork-per-connection)"

# fork    : a fresh process per connection, so a crash is that player's problem
# su=ctf  : challenge code never runs as root
# -T      : reap players who connect and wander off
#
# EXEC: takes a single program path with no shell quoting, which is why the
# banner lives in noco-serve rather than in an inline `sh -c`.
exec socat -T"${CHAL_TIMEOUT}" \
  TCP-LISTEN:1337,reuseaddr,fork,keepalive \
  EXEC:/usr/local/bin/noco-serve,su=ctf,pty,stderr,setsid,sigint,sane

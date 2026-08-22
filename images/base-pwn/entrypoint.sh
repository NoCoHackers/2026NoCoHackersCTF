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

# Root-owned, world-readable. The challenge runs as `ctf` and can read it but
# not rewrite it. We do not chown: the container drops CAP_CHOWN. A challenge
# that needs tighter permissions should arrange them itself.
printf '%s\n' "$FLAG" > /flag/flag.txt
chmod 644 /flag/flag.txt

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

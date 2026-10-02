#!/usr/bin/env bash
# Push challenges + event config to a running CTFd, leaving users/scores intact.
#
#   deploy/scoreboard/sync.sh                 # sync to production (.ctf/config url)
#   deploy/scoreboard/sync.sh --dev           # sync to the local `make dev` stack
#   deploy/scoreboard/sync.sh --dry-run       # config diff only, no challenge writes
#   deploy/scoreboard/sync.sh -c challenges/web/ghostdex   # one bundle
#   deploy/scoreboard/sync.sh -c challenges/misc/device/challenge.uart.yml
#
# The admin token comes from the environment, never the repo:
#   export CTFCLI_ACCESS_TOKEN=ctfd_xxx        # from CTFd: Settings -> Access Tokens
#
# What this does and does NOT touch:
#   challenges  -> created if new, updated in place if they already exist
#   event name/description/theme -> updated from event.yml
#   users, teams, submissions, scores -> NEVER touched
#
# Challenges are matched BY NAME. Renaming a challenge makes CTFd treat it as a
# brand-new one (the old solves stay attached to the old name). tools/validate.py
# guards against accidental renames via challenges/names.lock.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"

DEV=0 DRYRUN=0 ONE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)     DEV=1 ;;
    --dry-run) DRYRUN=1 ;;
    -c|--challenge) ONE="$2"; shift ;;
    *) echo "sync: unknown arg '$1'" >&2; exit 2 ;;
  esac
  shift
done

command -v ctf >/dev/null || { echo "sync: ctfcli not installed -> pip install ctfcli" >&2; exit 1; }
[[ -n "${CTFCLI_ACCESS_TOKEN:-}" ]] || { echo "sync: set CTFCLI_ACCESS_TOKEN (CTFd -> Settings -> Access Tokens)" >&2; exit 1; }

CFG_ARGS=()
if [[ $DEV -eq 1 ]]; then
  export CTFCLI_URL="${CTFCLI_URL:-http://ctf.localhost}"
  CFG_ARGS=(--dev)
  echo "sync: target = DEV ($CTFCLI_URL)"
else
  # The production URL is derived from event.yml's domain block (the single
  # source of truth); CTFCLI_URL can still override for a one-off target.
  if [[ -z "${CTFCLI_URL:-}" ]]; then
    export CTFCLI_URL="$(python3 tools/domains.py --print | awk '/NOCO_SCOREBOARD_URL/{print $2}')"
  fi
  echo "sync: target = ${CTFCLI_URL}  (production)"
fi

# --- challenges: install --force = create-if-new, update-if-exists ----------
# Neither create nor update reads or writes any user/solve data.
if [[ -n "$ONE" ]]; then
  manifest_output=$(python3 tools/chalbundle.py manifests "$ONE")
else
  manifest_output=$(python3 tools/chalbundle.py manifests)
fi
mapfile -t manifests <<< "$manifest_output"

echo "sync: pushing ${#manifests[@]} challenge(s) ..."
fail=0
for manifest in "${manifests[@]}"; do
  name=$(python3 tools/chalmeta.py "$manifest" | sed -n "s/^CHAL_TITLE=//p" | tr -d "'")
  if ctf challenge install --force -c "$manifest" >/tmp/noco-sync.$$ 2>&1; then
    if grep -q 'Syncing existing' /tmp/noco-sync.$$; then verb="updated"; else verb="created"; fi
    echo "  ok   $verb: $name"
  else
    echo "  FAIL $name"; sed 's/^/       | /' /tmp/noco-sync.$$; fail=1
  fi
done
rm -f /tmp/noco-sync.$$

# --- event config -----------------------------------------------------------
echo "sync: pushing event config from event.yml ..."
if [[ $DRYRUN -eq 1 ]]; then
  python3 tools/ctfd-config.py "${CFG_ARGS[@]}" --dry-run
else
  python3 tools/ctfd-config.py "${CFG_ARGS[@]}"
fi

[[ $fail -eq 0 ]] || { echo "sync: completed WITH FAILURES"; exit 1; }
echo "sync: done - scores and user data untouched"

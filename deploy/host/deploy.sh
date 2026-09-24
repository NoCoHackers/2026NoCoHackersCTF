#!/usr/bin/env bash
# Sync the minimum production files to one host, then optionally start its role.
set -euo pipefail

ROLE=${1:-}
TARGET=${2:-}
ACTION=${3:-up}
REMOTE_ROOT=${NOCO_INSTALL_ROOT:-/opt/noco}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

fatal() {
  echo "FATAL: $*" >&2
  exit 1
}

case "$ROLE" in
  chals|scoreboard) ;;
  *) fatal "usage: deploy.sh <chals|scoreboard> <user@host> [sync|up]" ;;
esac
case "$ACTION" in
  sync|up) ;;
  *) fatal "action must be sync or up" ;;
esac
[[ -n $TARGET ]] || fatal "an SSH target such as noco@203.0.113.10 is required"
command -v rsync >/dev/null || fatal "rsync is required on the operator machine"
command -v ssh >/dev/null || fatal "ssh is required on the operator machine"
[[ -f $ROOT/deploy/domains.env ]] || fatal "deploy/domains.env is missing; run make domains"

ssh "$TARGET" "mkdir -p '$REMOTE_ROOT/deploy'"
rsync -az --relative "$ROOT/./deploy/domains.env" "$TARGET:$REMOTE_ROOT/"

if [[ $ROLE == chals ]]; then
  rsync -az --delete \
    --exclude dns.env --exclude flags.env --exclude flags.enc.env \
    "$ROOT/deploy/chals/" "$TARGET:$REMOTE_ROOT/deploy/chals/"
  if [[ -f $ROOT/deploy/chals/flags.enc.env ]]; then
    rsync -az "$ROOT/deploy/chals/flags.enc.env" \
      "$TARGET:$REMOTE_ROOT/deploy/chals/flags.enc.env"
  fi
else
  rsync -az --delete \
    --exclude .env \
    "$ROOT/deploy/scoreboard/" "$TARGET:$REMOTE_ROOT/deploy/scoreboard/"
  ssh "$TARGET" "mkdir -p '$REMOTE_ROOT/images'"
  rsync -az --delete "$ROOT/images/caddy/" "$TARGET:$REMOTE_ROOT/images/caddy/"
fi

echo "Synced $ROLE files to $TARGET:$REMOTE_ROOT"
[[ $ACTION == up ]] || exit 0

if [[ $ROLE == chals ]]; then
  ssh "$TARGET" "
    set -eu
    test -s '$REMOTE_ROOT/deploy/chals/dns.env' || {
      echo 'FATAL: create $REMOTE_ROOT/deploy/chals/dns.env from dns.env.example' >&2
      exit 1
    }
    test -s '$REMOTE_ROOT/deploy/chals/flags.enc.env' || {
      echo 'FATAL: deploy/chals/flags.enc.env is missing locally and remotely' >&2
      exit 1
    }
    make -C '$REMOTE_ROOT/deploy/chals' up
    make -C '$REMOTE_ROOT/deploy/chals' ps
  "
else
  ssh "$TARGET" "
    set -eu
    test -s '$REMOTE_ROOT/deploy/scoreboard/.env' || {
      echo 'FATAL: create $REMOTE_ROOT/deploy/scoreboard/.env from .env.example' >&2
      exit 1
    }
    cd '$REMOTE_ROOT/deploy/scoreboard'
    docker compose up -d --build --remove-orphans
    docker compose ps
  "
fi

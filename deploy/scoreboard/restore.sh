#!/usr/bin/env bash
# Restore the scoreboard from a dump. Practice this BEFORE the event - an
# untested restore is a hope, not a plan.
#
#   ./restore.sh /var/backups/noco/ctfd-db-20261031T2300Z.sql.gz
set -euo pipefail
DUMP=${1:?usage: restore.sh <ctfd-db-*.sql.gz>}

if [[ -r /etc/noco/backup.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/noco/backup.env
  set +a
fi

read -rp "This overwrites the live CTFd database. Type the event name to confirm: " ok
[[ "$ok" == "nocohackers" ]] || { echo "aborted"; exit 1; }

docker compose stop ctfd
gunzip -c "$DUMP" | docker exec -i ctfd-db \
  mariadb -u root -p"${MYSQL_ROOT_PASSWORD:?}" ctfd
docker compose start ctfd
echo "restored from $DUMP"

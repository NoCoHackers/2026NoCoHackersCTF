#!/usr/bin/env bash
# Scoreboard backup. Run hourly from cron during the event, daily otherwise:
#   0 * * * * /opt/noco/deploy/scoreboard/backup.sh >> /var/log/noco-backup.log 2>&1
#
# Dumps the database and the uploads volume, keeps 48 locally, and pushes
# off-host. Off-host is the part people skip and then regret: a backup that
# lives on the box you are restoring is not a backup.
set -euo pipefail

# Cron does not read Compose's .env. Keep the root-only backup credential in a
# predictable file so the documented cron entry works non-interactively.
if [[ -r /etc/noco/backup.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/noco/backup.env
  set +a
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST=${NOCO_BACKUP_DIR:-/var/backups/noco}
REMOTE=${NOCO_BACKUP_REMOTE:-}        # e.g. rclone remote:noco-ctf
KEEP=${NOCO_BACKUP_KEEP:-48}

mkdir -p "$DEST"

echo "[$STAMP] dumping database"
docker exec ctfd-db mariadb-dump \
  -u root -p"${MYSQL_ROOT_PASSWORD:?set in /etc/noco/backup.env}" \
  --single-transaction --quick --routines ctfd \
  | gzip -9 > "$DEST/ctfd-db-$STAMP.sql.gz"

echo "[$STAMP] archiving uploads"
docker run --rm \
  -v noco-scoreboard-ctfd-uploads:/uploads:ro \
  -v "$DEST":/out alpine \
  tar czf "/out/ctfd-uploads-$STAMP.tar.gz" -C /uploads .

if [[ -n "$REMOTE" ]]; then
  echo "[$STAMP] pushing off-host to $REMOTE"
  rclone copy "$DEST/ctfd-db-$STAMP.sql.gz"      "$REMOTE" --no-traverse
  rclone copy "$DEST/ctfd-uploads-$STAMP.tar.gz" "$REMOTE" --no-traverse
else
  echo "[$STAMP] WARNING: NOCO_BACKUP_REMOTE unset - backups are local only"
fi

# Prune
ls -1t "$DEST"/ctfd-db-*.sql.gz      2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm --
ls -1t "$DEST"/ctfd-uploads-*.tar.gz 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm --

echo "[$STAMP] done"

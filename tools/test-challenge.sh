#!/usr/bin/env bash
# Build one challenge, boot it, run its autosolve, prove the flag comes back.
# This is the gate every challenge passes on every pull request.
#
#   tools/test-challenge.sh challenges/web/haunted-brewery
#   NOCO_KEEP=1 tools/test-challenge.sh ...   # leave the container up to poke at
#
# Exits non-zero with a readable reason on any failure.
set -euo pipefail

CHAL_DIR=${1:?usage: test-challenge.sh challenges/<cat>/<slug>}
CHAL_DIR=${CHAL_DIR%/}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

[[ -f "$CHAL_DIR/challenge.yml" ]] || { echo "no challenge.yml in $CHAL_DIR" >&2; exit 1; }

eval "$(python3 tools/chalmeta.py "$CHAL_DIR")"
NAME=$(basename "$CHAL_DIR")
CID=""

cleanup() {
  [[ -z "$CID" ]] && return
  if [[ "${NOCO_KEEP:-}" == "1" ]]; then
    echo "--- container kept as $CID (NOCO_KEEP=1)"
  else
    docker logs "$CID" 2>&1 | tail -30 | sed 's/^/    log| /' || true
    docker rm -f "$CID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$CHAL_KIND" == "static" ]]; then
  echo "==> $NAME is handout-only; nothing to boot"
  exit 0
fi

echo "==> building $NAME"
IMG="noco-test/$NAME:ci"
docker build -q -f "$CHAL_DIR/Dockerfile" -t "$IMG" . >/dev/null

echo "==> flag-leak scan"
# The flag must arrive at runtime. If it is visible in the built filesystem or
# in the build history, anyone who can pull the image gets free points.
if docker history --no-trunc "$IMG" | grep -qF -- "$CHAL_FLAG"; then
  echo "FAIL: flag appears in the image build history" >&2; exit 1
fi
# -xdev keeps us on the image's own filesystem; without it grep wanders into
# /proc and /dev/zero and never comes back.
LEAK=$(docker run --rm --entrypoint sh "$IMG" -c \
  "find / -xdev -type f -size -8M \
     ! -path '/proc/*' ! -path '/sys/*' ! -path '/dev/*' \
     -exec grep -lF -- '$CHAL_FLAG' {} + 2>/dev/null | head -3" || true)
if [[ -n "$LEAK" ]]; then
  echo "FAIL: flag is baked into the image filesystem:" >&2
  echo "$LEAK" | sed 's/^/  /' >&2
  exit 1
fi

echo "==> booting"
# Mirror the writable paths the generated production compose grants, so a
# challenge that passes CI cannot fail on the host for a mount it never had.
EXTRA=()
if [[ "$CHAL_KIND" == "web" ]]; then
  EXTRA=(--tmpfs /var/run --tmpfs /var/cache/nginx
         --tmpfs "/srv/www:size=64m,uid=101,gid=101,mode=0755")
else
  # Matches the caps the generated production compose grants tcp challenges.
  EXTRA=(--tmpfs "/flag:size=1m"
         --cap-add SETUID --cap-add SETGID --cap-add SETPCAP)
fi

CID=$(docker run -d -P -e FLAG="$CHAL_FLAG" \
        --read-only --tmpfs /tmp "${EXTRA[@]}" \
        --security-opt no-new-privileges:true --cap-drop ALL \
        --memory 512m --pids-limit 256 "$IMG")

if [[ "$CHAL_KIND" == "web" ]]; then
  PORT=$(docker port "$CID" 8080/tcp | head -1 | sed 's/.*://')
  TARGET="http://127.0.0.1:$PORT"
  probe() { curl -fsS -o /dev/null "$TARGET$CHAL_HPATH"; }
else
  PORT=$(docker port "$CID" 1337/tcp | head -1 | sed 's/.*://')
  TARGET="127.0.0.1 $PORT"
  probe() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }
fi

for i in $(seq 1 30); do
  probe && break
  if [[ $i -eq 30 ]]; then echo "FAIL: never became healthy at $TARGET" >&2; exit 1; fi
  sleep 1
done
echo "    healthy at $TARGET"

echo "==> autosolve"
GOT=$(cd "$CHAL_DIR" && TARGET="$TARGET" timeout 180 "./$CHAL_SOLVE" 2>/dev/null \
      | tr -d '\r' | tail -1)

if [[ "$GOT" != "$CHAL_FLAG" ]]; then
  echo "FAIL: autosolve returned '$GOT' but challenge.yml declares '$CHAL_FLAG'" >&2
  exit 1
fi

echo "==> PASS  $NAME"

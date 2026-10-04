#!/usr/bin/env bash
# Build one challenge bundle, then prove every scoreboard entry independently.
# Runnable entries each get a fresh container so solves cannot share state.
set -euo pipefail

CHAL_DIR=${1:?usage: test-challenge.sh challenges/<cat>/<slug>}
CHAL_DIR=${CHAL_DIR%/}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

[[ -f "$CHAL_DIR/challenge.yml" ]] || { echo "no challenge.yml in $CHAL_DIR" >&2; exit 1; }
MANIFESTS=()
while IFS= read -r manifest; do
  MANIFESTS+=("$manifest")
done < <(python3 tools/chalbundle.py manifests "$CHAL_DIR")
[[ ${#MANIFESTS[@]} -gt 0 ]] || { echo "no challenge manifests in $CHAL_DIR" >&2; exit 1; }

eval "$(python3 tools/chalmeta.py "$CHAL_DIR")"
BUNDLE_KIND=$CHAL_KIND
BUNDLE_HPATH=$CHAL_HPATH
NAME=$(basename "$CHAL_DIR")
CID=""

IDS=() FLAGS=() SOLVES=() TITLES=()
ENV_ARGS=()
for manifest in "${MANIFESTS[@]}"; do
  eval "$(python3 tools/chalmeta.py "$manifest")"
  IDS+=("$CHAL_ID")
  FLAGS+=("$CHAL_FLAG")
  SOLVES+=("$CHAL_SOLVE")
  TITLES+=("$CHAL_TITLE")
  if [[ "$CHAL_ID" == "main" ]]; then
    ENV_ARGS+=(-e "FLAG=$CHAL_FLAG")
  fi
done
if [[ ${#MANIFESTS[@]} -gt 1 ]]; then
  for i in "${!MANIFESTS[@]}"; do
    eval "$(python3 tools/chalmeta.py "${MANIFESTS[$i]}")"
    ENV_ARGS+=(-e "$CHAL_CONTAINER_FLAG_VAR=${FLAGS[$i]}")
  done
fi

cleanup() {
  [[ -z "$CID" ]] && return
  if [[ "${NOCO_KEEP:-}" == "1" ]]; then
    echo "--- container kept as $CID (NOCO_KEEP=1)"
  else
    docker logs "$CID" 2>&1 | tail -30 | sed 's/^/    log| /' || true
    docker rm -f "$CID" >/dev/null 2>&1 || true
  fi
  CID=""
}
trap cleanup EXIT

count_external_tests() {
  python3 - "$1" <<'PY'
import sys
import unittest

suite = unittest.defaultTestLoader.discover(sys.argv[1])
print(suite.countTestCases())
PY
}

external_origin() {
  python3 - "$1" <<'PY'
import json
import sys

print(json.loads(sys.argv[1])["origin"])
PY
}

external_snapshot() {
  python3 - "$ROOT" "$CHAL_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
bundle_dir = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root / "tools"))

from chalbundle import load_bundle
from external import live_snapshot

import json

print(json.dumps(live_snapshot(load_bundle(bundle_dir)), sort_keys=True, separators=(",", ":")))
PY
}

check_external_snapshot() {
  python3 - "$ROOT" "$CHAL_DIR" "$1" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
bundle_dir = Path(sys.argv[2]).resolve()
snapshot = sys.argv[3]
sys.path.insert(0, str(root / "tools"))

from chalbundle import load_bundle
from external import validate_live_snapshot

import json

errors = validate_live_snapshot(load_bundle(bundle_dir), json.loads(snapshot))
if errors:
    for error in errors:
        print(error, file=sys.stderr)
    raise SystemExit(1)
PY
}

write_external_receipt() {
  python3 - "$ROOT" "$CHAL_DIR" "$1" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
bundle_dir = Path(sys.argv[2]).resolve()
snapshot = sys.argv[3]
sys.path.insert(0, str(root / "tools"))

from external import write_receipt_snapshot

path = write_receipt_snapshot(bundle_dir, json.loads(snapshot))
print(path.name)
PY
}

run_external_solver() {
  local solve=$1 target=$2
  python3 - "$CHAL_DIR" "$solve" "$target" <<'PY'
import os
import subprocess
import sys

cwd, solve, target = sys.argv[1:]
env = os.environ.copy()
env["TARGET"] = target
env["NOCO_EXTERNAL_LIVE"] = "1"
command = [os.path.join(".", solve)]
try:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                            text=True, timeout=180)
except subprocess.TimeoutExpired:
    sys.stderr.write(f"solver exceeded the hard 180-second limit: {solve}\n")
    raise SystemExit(124)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
PY
}

solve_entry() {
  local index=$1 target=${2:-} got
  echo "==> autosolve ${IDS[$index]}: ${TITLES[$index]}"
  if [[ -n "$target" ]]; then
    got=$(cd "$CHAL_DIR" && TARGET="$target" timeout 180 "./${SOLVES[$index]}" 2>/dev/null \
          | tr -d '\r' | tail -1)
  else
    got=$(cd "$CHAL_DIR" && env -u TARGET timeout 180 "./${SOLVES[$index]}" 2>/dev/null \
          | tr -d '\r' | tail -1)
  fi
  if [[ "$got" != "${FLAGS[$index]}" ]]; then
    echo "FAIL: ${MANIFESTS[$index]} autosolve returned '$got' but declares '${FLAGS[$index]}'" >&2
    exit 1
  fi
}

if [[ "$BUNDLE_KIND" == "external" ]]; then
  if [[ "${NOCO_EXTERNAL_LIVE:-}" != "1" ]]; then
    TEST_DIR="$CHAL_DIR/solution/tests"
    [[ -d "$TEST_DIR" ]] || {
      echo "FAIL: external bundles must define an offline contract suite at $TEST_DIR" >&2
      exit 1
    }
    TEST_COUNT=$(count_external_tests "$TEST_DIR") || {
      echo "FAIL: could not discover external contract tests at $TEST_DIR" >&2
      exit 1
    }
    [[ "$TEST_COUNT" =~ ^[0-9]+$ ]] || {
      echo "FAIL: invalid unittest discovery count for $TEST_DIR" >&2
      exit 1
    }
    [[ "$TEST_COUNT" -gt 0 ]] || {
      echo "FAIL: external contract suite at $TEST_DIR must define at least one unittest" >&2
      exit 1
    }
    echo "==> external offline contract suite ($TEST_COUNT tests)"
    python3 -m unittest discover -s "$TEST_DIR" -v
    echo "==> offline contract only, live solve not attempted"
    exit 0
  fi

  SNAPSHOT=$(external_snapshot)
  ORIGIN=$(external_origin "$SNAPSHOT")
  echo "==> live external verification at $ORIGIN"
  for i in "${!MANIFESTS[@]}"; do
    echo "==> external autosolve ${IDS[$i]}: ${TITLES[$i]}"
    got=$(run_external_solver "${SOLVES[$i]}" "$ORIGIN" 2>/dev/null | tr -d '\r' | tail -1) || {
      echo "FAIL: ${MANIFESTS[$i]} live solver exited non-zero" >&2
      exit 1
    }
    if [[ "$got" != "${FLAGS[$i]}" ]]; then
      echo "FAIL: ${MANIFESTS[$i]} live solver did not return its declared flag" >&2
      exit 1
    fi
    check_external_snapshot "$SNAPSHOT" || exit 1
  done
  check_external_snapshot "$SNAPSHOT" || exit 1
  RECEIPT=$(write_external_receipt "$SNAPSHOT")
  echo "==> wrote $RECEIPT after ${#MANIFESTS[@]} live solve(s)"
  exit 0
fi

if [[ "$BUNDLE_KIND" == "static" ]]; then
  echo "==> $NAME is static; running ${#MANIFESTS[@]} autosolve(s)"
  for i in "${!MANIFESTS[@]}"; do solve_entry "$i"; done
  echo "==> PASS  $NAME (${#MANIFESTS[@]} entries)"
  exit 0
fi

echo "==> building $NAME"
IMG="noco-test/$NAME:ci"
docker build -q -f "$CHAL_DIR/Dockerfile" -t "$IMG" . >/dev/null

echo "==> flag-leak scan (${#FLAGS[@]} flags)"
for flag in "${FLAGS[@]}"; do
  if docker history --no-trunc "$IMG" | grep -qF -- "$flag"; then
    echo "FAIL: flag appears in the image build history" >&2; exit 1
  fi
  LEAK=$(docker run --rm --entrypoint sh -e SCAN_FLAG="$flag" "$IMG" -c \
    'find / -xdev -type f -size -8M \
       ! -path "/proc/*" ! -path "/sys/*" ! -path "/dev/*" \
       -exec grep -lF -- "$SCAN_FLAG" {} + 2>/dev/null | head -3' || true)
  if [[ -n "$LEAK" ]]; then
    echo "FAIL: flag is baked into the image filesystem:" >&2
    echo "$LEAK" | sed 's/^/  /' >&2
    exit 1
  fi
done

EXTRA=()
if [[ "$BUNDLE_KIND" == "web" ]]; then
  EXTRA=(--tmpfs /var/run --tmpfs /var/cache/nginx
         --tmpfs "/srv/www:size=64m,uid=101,gid=101,mode=0755")
else
  EXTRA=(--tmpfs "/flag:size=1m"
         --cap-add SETUID --cap-add SETGID --cap-add SETPCAP)
fi

for i in "${!MANIFESTS[@]}"; do
  echo "==> booting fresh container for ${IDS[$i]}"
  CID=$(docker run -d -P "${ENV_ARGS[@]}" \
          --read-only --tmpfs /tmp "${EXTRA[@]}" \
          --security-opt no-new-privileges:true --cap-drop ALL \
          --memory 512m --pids-limit 256 "$IMG")

  if [[ "$BUNDLE_KIND" == "web" ]]; then
    PORT=$(docker port "$CID" 8080/tcp | head -1 | sed 's/.*://')
    TARGET="http://127.0.0.1:$PORT"
    probe() { curl -fsS -o /dev/null "$TARGET$BUNDLE_HPATH"; }
  else
    PORT=$(docker port "$CID" 1337/tcp | head -1 | sed 's/.*://')
    TARGET="127.0.0.1 $PORT"
    probe() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }
  fi

  for attempt in $(seq 1 30); do
    probe && break
    if [[ $attempt -eq 30 ]]; then
      echo "FAIL: never became healthy at $TARGET" >&2; exit 1
    fi
    sleep 1
  done
  echo "    healthy at $TARGET"
  solve_entry "$i" "$TARGET"
  cleanup
done

echo "==> PASS  $NAME (${#MANIFESTS[@]} entries)"

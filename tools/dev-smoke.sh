#!/usr/bin/env bash
# Smoke-test a running local environment (`make dev` must be up).
#
# Verifies the INTEGRATION that per-challenge autosolve can't: that Traefik
# routes every web challenge by hostname, that CTFd answers through the proxy,
# and that every TCP challenge accepts connections on its published port. It
# does not re-solve challenges - the autosolve job already does that.
#
# Endpoints are derived from the generated dev files, so this stays in sync as
# challenges come and go. Exits non-zero on the first failure.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
DYN=deploy/dev/traefik-dynamic.yml
DEV=deploy/dev/docker-compose.dev.yml
BASE=http://127.0.0.1
fails=0

[[ -f "$DYN" && -f "$DEV" ]] || { echo "smoke: dev files missing - run 'make dev' first" >&2; exit 2; }

note() { printf '  %-7s %s\n' "$1" "$2"; }
ok()   { note "ok" "$1"; }
bad()  { note "FAIL" "$1"; fails=$((fails+1)); }

# curl through Traefik with a Host header; no DNS needed. Retries for slow boots.
http_host() {  # host path expected_code [tries]
  local host=$1 path=$2 want=$3 tries=${4:-1} code
  for _ in $(seq 1 "$tries"); do
    code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $host" "$BASE$path" || true)
    [[ "$code" == "$want" ]] && { echo "$code"; return 0; }
    sleep 2
  done
  echo "$code"; return 1
}

echo "== scoreboard =="
# CTFd initialises MariaDB on first boot; give it up to ~90s.
if code=$(http_host ctf.localhost /setup 200 45); then
  ok "CTFd reachable at http://ctf.localhost (/setup $code)"
else
  bad "CTFd not reachable through Traefik (last code: ${code:-none})"
fi

echo "== web challenges (Traefik host routing) =="
web_hosts=$(python3 - "$DYN" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
for name, r in (d.get("http", {}).get("routers", {}) or {}).items():
    if name == "ctfd":
        continue
    rule = r.get("rule", "")
    if "Host(`" in rule:
        print(rule.split("Host(`", 1)[1].split("`", 1)[0])
PY
)
if [[ -z "$web_hosts" ]]; then
  note "note" "no web challenges routed"
else
  for h in $web_hosts; do
    if code=$(http_host "$h" / 200 10); then ok "http://$h ($code)"
    else bad "http://$h did not return 200 (last: ${code:-none})"; fi
  done
fi

echo "== tcp challenges (published ports) =="
tcp_ports=$(grep -hoE '[0-9]{5}:1337' "$DEV" | sed 's/:1337//' | sort -u || true)
if [[ -z "$tcp_ports" ]]; then
  note "note" "no tcp challenges published"
else
  for p in $tcp_ports; do
    if timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/$p" 2>/dev/null; then
      ok "nc localhost $p accepts connections"
    else
      bad "port $p not accepting connections"
    fi
  done
fi

echo
if [[ $fails -eq 0 ]]; then
  echo "smoke: PASS - the full stack is up and routing"
else
  echo "smoke: FAIL - $fails check(s) failed"
  echo "--- recent container state ---"
  docker compose -p noco-dev -f deploy/dev/compose.infra.yml -f "$DEV" ps 2>/dev/null || true
fi
exit $(( fails > 0 ? 1 : 0 ))

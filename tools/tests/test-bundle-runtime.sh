#!/usr/bin/env bash
# Docker integration fixture for static, base-web, and base-pwn bundle behavior.
# Run after tools/build-base-images.sh. Temporary challenge bundles are removed.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
STATIC=challenges/misc/bundle-runtime-test-static
WEB=challenges/misc/bundle-runtime-test-web
PWN=challenges/misc/bundle-runtime-test-pwn
cleanup() { rm -rf "$STATIC" "$WEB" "$PWN"; }
trap cleanup EXIT
cleanup

write_common_solutions() {
  local dir=$1 supplemental=$2
  mkdir -p "$dir/solution"
  printf 'runtime fixture\n' > "$dir/solution/writeup.md"
  cat > "$dir/solution/solve.sh" <<'SH'
#!/bin/sh
python3 -c 'import yaml; print(yaml.safe_load(open("challenge.yml"))["flags"][0])'
SH
  cat > "$dir/solution/solve-uart-debug.sh" <<SH
#!/bin/sh
python3 -c 'import yaml; print(yaml.safe_load(open("$supplemental"))["flags"][0])'
SH
  chmod +x "$dir/solution/solve.sh" "$dir/solution/solve-uart-debug.sh"
}

# Static entries prove handout-only bundles no longer bypass their autosolves.
mkdir -p "$STATIC"
cat > "$STATIC/challenge.yml" <<'YML'
name: Bundle Runtime Static Main
author: test
category: misc
description: ephemeral fixture
value: 100
flags: ['noco{runtime_static_main}']
files: []
state: hidden
x-noco:
  kind: static
  autosolve: solution/solve.sh
YML
cat > "$STATIC/challenge.uart-debug.yml" <<'YML'
name: Bundle Runtime Static UART
author: test
category: misc
description: ephemeral fixture
value: 100
flags: ['noco{runtime_static_uart}']
files: []
state: hidden
x-noco:
  autosolve: solution/solve-uart-debug.sh
YML
write_common_solutions "$STATIC" challenge.uart-debug.yml
tools/test-challenge.sh "$STATIC"

# base-web must preserve __FLAG__ and render named, normalized entry tokens.
mkdir -p "$WEB/src" "$WEB/solution"
cat > "$WEB/challenge.yml" <<'YML'
name: Bundle Runtime Web Main
author: test
category: misc
description: ephemeral fixture
value: 100
flags: ['noco{runtime_web_main}']
files: []
state: hidden
x-noco:
  kind: web
  subdomain: bundle-runtime-test
  autosolve: solution/solve.sh
YML
cat > "$WEB/challenge.uart-debug.yml" <<'YML'
name: Bundle Runtime Web UART
author: test
category: misc
description: ephemeral fixture
value: 100
flags: ['noco{runtime_web_uart}']
files: []
state: hidden
x-noco:
  autosolve: solution/solve-uart-debug.sh
YML
cat > "$WEB/Dockerfile" <<'DOCKER'
FROM ghcr.io/nocohackers/chal-web:2026
COPY challenges/misc/bundle-runtime-test-web/src/ /srv/app/
ENV CHAL_NAME="Bundle Runtime Web" CHAL_CATEGORY="misc"
DOCKER
printf '<a href="/legacy.txt">fixture</a>\n' > "$WEB/src/index.html"
printf '__FLAG__\n' > "$WEB/src/legacy.txt"
printf '__FLAG_MAIN__\n' > "$WEB/src/main.txt"
printf '__FLAG_UART_DEBUG__\n' > "$WEB/src/uart.txt"
cat > "$WEB/solution/solve.sh" <<'SH'
#!/bin/sh
set -eu
legacy=$(curl -fsS "$TARGET/legacy.txt")
main=$(curl -fsS "$TARGET/main.txt")
[ "$legacy" = "$main" ]
printf '%s\n' "$main"
SH
cat > "$WEB/solution/solve-uart-debug.sh" <<'SH'
#!/bin/sh
curl -fsS "$TARGET/uart.txt"
SH
chmod +x "$WEB/solution/"solve*.sh
printf 'runtime fixture\n' > "$WEB/solution/writeup.md"
tools/test-challenge.sh "$WEB"

# base-pwn must preserve /flag.txt and add a kebab-cased named flag file.
mkdir -p "$PWN/src" "$PWN/solution"
cat > "$PWN/challenge.yml" <<'YML'
name: Bundle Runtime Pwn Main
author: test
category: misc
description: ephemeral fixture
value: 100
flags: ['noco{runtime_pwn_main}']
files: []
state: hidden
x-noco:
  kind: tcp
  port: 30099
  autosolve: solution/solve.sh
YML
cat > "$PWN/challenge.uart-debug.yml" <<'YML'
name: Bundle Runtime Pwn UART
author: test
category: misc
description: ephemeral fixture
value: 100
flags: ['noco{runtime_pwn_uart}']
files: []
state: hidden
x-noco:
  autosolve: solution/solve-uart-debug.sh
YML
cat > "$PWN/Dockerfile" <<'DOCKER'
FROM ghcr.io/nocohackers/chal-pwn:2026
COPY --chmod=755 challenges/misc/bundle-runtime-test-pwn/src/chal.sh /srv/chal
ENV CHAL_NAME="Bundle Runtime Pwn"
DOCKER
cat > "$PWN/src/chal.sh" <<'SH'
#!/bin/sh
cat /flag.txt /flag/main.txt /flag/uart-debug.txt
SH
cat > "$PWN/solution/solve.sh" <<'SH'
#!/bin/bash
set -euo pipefail
read -r host port <<<"$TARGET"
nc -w 3 "$host" "$port" | grep -oE 'noco\{[^}]+\}' | head -1
SH
cat > "$PWN/solution/solve-uart-debug.sh" <<'SH'
#!/bin/bash
set -euo pipefail
read -r host port <<<"$TARGET"
nc -w 3 "$host" "$port" | grep -oE 'noco\{[^}]+\}' | tail -1
SH
chmod +x "$PWN/solution/"solve*.sh
printf 'runtime fixture\n' > "$PWN/solution/writeup.md"
tools/test-challenge.sh "$PWN"

echo "bundle runtime fixtures: PASS"

#!/usr/bin/env bash
# Build the three base images and tag them the way challenge Dockerfiles
# expect. Run this before building any challenge locally; CI runs it too.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=${NOCO_TAG:-2026}
REG=${NOCO_REGISTRY:-ghcr.io/nocohackers}

sh tools/build-theme.sh

build() {
  echo "==> $REG/$1:$TAG"
  docker build -q -f "images/$2/Dockerfile" -t "$REG/$1:$TAG" . >/dev/null
}

build chal-theme theme-assets
build chal-web   base-web
build chal-pwn   base-pwn

# The scoreboard edge proxy: plain Caddy plus the rate_limit module. Its build
# context is self-contained (no repo files), unlike the challenge base images.
echo "==> $REG/caddy-ratelimit:$TAG"
docker build -q -t "$REG/caddy-ratelimit:$TAG" images/caddy >/dev/null

echo "base images ready at tag :$TAG"

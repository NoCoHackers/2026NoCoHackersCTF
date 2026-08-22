# ghcr.io/nocohackers/caddy-ratelimit:2026
#
# Stock caddy:2-alpine has no rate limiting. The scoreboard Caddyfile uses the
# `rate_limit` directive to cap /login, /register, and flag submissions at the
# edge, which comes from a third-party module that must be compiled in. This
# image is plain Caddy plus that one module - nothing else changes.
#
# Build context is THIS directory (no repo files needed):
#   docker build -t ghcr.io/nocohackers/caddy-ratelimit:2026 images/caddy
FROM caddy:2.9-builder-alpine AS builder
RUN xcaddy build \
      --with github.com/mholt/caddy-ratelimit@v0.1.0

FROM caddy:2.9-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
# Prove the module is present at build time so a broken build fails here,
# not at deploy.
RUN caddy list-modules | grep -q http.handlers.rate_limit

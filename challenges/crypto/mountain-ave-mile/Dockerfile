# Build context is the REPO ROOT (see compose.yml / deploy/chals/generate.py).
#
# Not base-web: the timing office needs a real claim endpoint, so this is a
# stdlib-Python server with the shared theme grafted in from chal-theme.
FROM ghcr.io/nocohackers/chal-theme:2026 AS theme

FROM python:3.12-alpine

# Unprivileged, like everything else the event runs.
RUN addgroup -S ctf && adduser -S -G ctf -u 1000 ctf

WORKDIR /srv/app
COPY --from=theme /theme /srv/theme
COPY challenges/crypto/mountain-ave-mile/src/ /srv/app/

USER ctf
ENV FLAG="" \
    CHAL_NAME="Midnight Mountain Ave Mile" \
    CHAL_CATEGORY="crypto" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["python3", "-u", "server.py"]

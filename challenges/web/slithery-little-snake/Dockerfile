# Build context is the repo root so the shared theme is available.
FROM ghcr.io/nocohackers/chal-theme:2026 AS theme
FROM python:3.12-alpine

WORKDIR /srv/app
COPY --from=theme /theme /srv/app/theme
COPY challenges/web/slithery-little-snake/src/ /srv/app/

RUN adduser -D -H -u 10001 snake
USER snake
ENV CHAL_NAME="slithery little snake" CHAL_CATEGORY="web"
EXPOSE 8080
CMD ["python3", "server.py"]

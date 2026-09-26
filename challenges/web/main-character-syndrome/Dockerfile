# Build context is the repository root. Keep the theme in sync with the event.
FROM ghcr.io/nocohackers/chal-theme:2026 AS theme
FROM python:3.12-alpine

RUN apk add --no-cache jq && addgroup -S ctf && adduser -S -G ctf ctf
COPY --from=theme /theme /srv/theme
COPY challenges/web/main-character-syndrome/src/ /srv/app/

ENV PYTHONDONTWRITEBYTECODE=1
USER ctf
EXPOSE 8080
CMD ["python3", "/srv/app/server.py"]

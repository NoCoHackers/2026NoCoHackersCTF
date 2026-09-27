# Traefik terminates HTTPS; the app and its syscall-only jail run in the
# challenge container with the generated read-only/cap-drop hardening.
FROM ghcr.io/nocohackers/chal-theme:2026 AS theme
FROM python:3.12-alpine AS jail
RUN apk add --no-cache gcc musl-dev linux-headers
COPY challenges/web/main-character-syndrome/src/jail.c /tmp/jail.c
RUN gcc -O2 -Wall -Wextra -o /tmp/noco-jail /tmp/jail.c

FROM python:3.12-alpine
RUN apk add --no-cache jq && addgroup -S ctf && adduser -S -G ctf ctf
COPY --from=theme /theme /srv/theme
COPY --from=jail /tmp/noco-jail /usr/local/bin/noco-jail
COPY challenges/web/main-character-syndrome/src/ /srv/app/
COPY challenges/web/main-character-syndrome/handout/cache-de-spectre /srv/artifact/cache-de-spectre

ENV PYTHONDONTWRITEBYTECODE=1
USER ctf
EXPOSE 8080
CMD ["python3", "/srv/app/server.py"]

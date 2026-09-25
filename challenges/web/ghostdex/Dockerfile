# Build context is the REPO ROOT (so the theme is reachable). See compose.yml.
FROM ghcr.io/nocohackers/chal-web:2026

COPY challenges/web/ghostdex/src/ /srv/app/

ENV CHAL_NAME="Ghost in the Index" \
    CHAL_CATEGORY="web"

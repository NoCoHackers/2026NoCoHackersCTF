# Build context is the REPO ROOT (so the theme is reachable). See compose.yml.
FROM ghcr.io/nocohackers/chal-web:2026

COPY challenges/TEMPLATE/src/ /srv/app/

ENV CHAL_NAME="Template Challenge" \
    CHAL_CATEGORY="web"

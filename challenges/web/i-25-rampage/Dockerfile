# Build context is the repo root so the shared theme is available.
FROM ghcr.io/nocohackers/chal-theme:2026 AS theme
FROM python:3.12-alpine

WORKDIR /srv/app
COPY --from=theme /theme /srv/app/theme
COPY challenges/web/i-25-rampage/src/ /srv/app/

RUN adduser -D -H -u 10001 rampage
USER rampage
ENV CHAL_NAME="I-25 Rampage" CHAL_CATEGORY="web"
EXPOSE 8080
CMD ["python3", "server.py"]

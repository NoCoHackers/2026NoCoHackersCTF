# ghcr.io/nocohackers/chal-theme:2026
#
# Nothing but the theme, so ANY challenge — Flask, Rails, Go, PHP, whatever —
# can graft it on as a build stage without inheriting our base image:
#
#   FROM ghcr.io/nocohackers/chal-theme:2026 AS theme
#   FROM python:3.12-slim
#   COPY --from=theme /theme /app/static/theme
#
# Build context is the REPO ROOT, not this directory.
FROM scratch
COPY theme/theme.bundle.css theme/favicon.svg theme/banner.txt /theme/
COPY theme/partials/ /theme/partials/

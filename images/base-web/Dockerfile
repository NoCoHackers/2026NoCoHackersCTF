# ghcr.io/nocohackers/chal-web:2026
#
# For static and mostly-static web challenges. Theme is already mounted at
# /theme, nginx runs unprivileged on 8080, SSI is on so the header and footer
# partials just work, and the flag is injected at RUNTIME.
#
#   FROM ghcr.io/nocohackers/chal-web:2026
#   COPY challenges/web/my-slug/src/ /srv/app/
#   ENV CHAL_NAME="My Slug" CHAL_CATEGORY="web"
#
# Build context is the REPO ROOT.
#
# Layout note: authors write to /srv/app, which stays read-only. At boot the
# entrypoint renders /srv/app into /srv/www (a tmpfs) and nginx serves from
# there. That is what lets the container run with `read_only: true` while still
# templating the flag in at runtime.
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
COPY images/base-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY images/base-web/entrypoint.sh /usr/local/bin/noco-entrypoint
COPY theme/theme.bundle.css theme/favicon.svg /srv/theme/
COPY theme/partials/header.html theme/partials/footer.html /srv/app/

# Two workers, not one-per-core. Twenty-five containers each spawning sixteen
# workers is how you hit pids_limit on a 4-vCPU box for no throughput at all.
RUN sed -i 's/^worker_processes.*/worker_processes 2;/' /etc/nginx/nginx.conf \
 && chmod +x /usr/local/bin/noco-entrypoint \
 && mkdir -p /srv/app /srv/www \
 && chown -R 101:101 /srv

USER 101
EXPOSE 8080

# Flags are never baked into a layer. See AGENTS.md, "Flag handling".
ENV FLAG="" CHAL_NAME="Untitled" CHAL_CATEGORY="misc"

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/usr/local/bin/noco-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]

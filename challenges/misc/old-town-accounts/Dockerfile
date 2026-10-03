FROM fedora:43

RUN dnf -y --setopt=install_weak_deps=False install python3 shadow-utils zlib \
    && dnf clean all \
    && useradd --system --uid 10001 --home-dir /nonexistent \
       --shell /sbin/nologin ctf

WORKDIR /opt/old-town-accounts
COPY --chown=ctf:ctf challenges/misc/old-town-accounts/src/ ./

ENV PORT=8080 \
    NOCO_INSTANCE_DIR=/tmp/instances \
    NOCO_MASTER=/opt/old-town-accounts/master.rk \
    NOCO_SIM=/opt/old-town-accounts/bin/pdp11 \
    NOCO_POOL_INITIAL=5 \
    NOCO_POOL_MAX=20 \
    NOCO_IDLE_SECS=21600 \
    NOCO_SESSION_TTL=43200 \
    NOCO_RESET_COOLDOWN=30 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER ctf
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=45s --retries=3 \
    CMD python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=2)'

CMD ["python3", "/opt/old-town-accounts/gateway.py"]

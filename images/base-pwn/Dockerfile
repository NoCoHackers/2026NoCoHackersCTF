# ghcr.io/nocohackers/chal-pwn:2026
#
# For pwn / "just netcat to it" challenges. socat forks a FRESH process per
# connection, so one player crashing or corrupting the challenge cannot affect
# anyone else. That is deliberately instead-of per-team instancing - see
# INFRASTRUCTURE.md, "Isolation".
#
#   FROM ghcr.io/nocohackers/chal-pwn:2026
#   COPY --chmod=755 challenges/pwn/my-slug/chal /srv/chal
#   ENV CHAL_NAME="The Armory"
#
# Build context is the REPO ROOT.
#
# The flag lives at /flag.txt, which is a symlink into the /flag tmpfs. That is
# what lets the container run with a read-only root filesystem while still
# receiving its flag at runtime. Run it with `--tmpfs /flag`.
FROM ubuntu:22.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends socat ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 -s /usr/sbin/nologin ctf \
 && mkdir -p /flag \
 && ln -sf /flag/flag.txt /flag.txt

COPY images/base-pwn/entrypoint.sh /usr/local/bin/noco-entrypoint
COPY images/base-pwn/serve.sh      /usr/local/bin/noco-serve
COPY theme/banner.txt /srv/banner.txt
RUN chmod +x /usr/local/bin/noco-entrypoint /usr/local/bin/noco-serve

WORKDIR /srv

ENV FLAG="" CHAL_NAME="Untitled" CHAL_BIN="/srv/chal" CHAL_TIMEOUT="120"
EXPOSE 1337

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD timeout 4 socat -u /dev/null TCP:127.0.0.1:1337 || exit 1

ENTRYPOINT ["/usr/local/bin/noco-entrypoint"]

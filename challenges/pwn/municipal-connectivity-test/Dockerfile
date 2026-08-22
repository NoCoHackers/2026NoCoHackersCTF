# Build context is the REPO ROOT.
FROM ubuntu:22.04 AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
COPY challenges/pwn/municipal-connectivity-test/src/chal.c /src/chal.c
RUN gcc -O2 -Wall -Wextra -Werror \
    -D_FORTIFY_SOURCE=2 -fstack-protector-strong -fPIE -pie \
    -Wl,-z,relro,-z,now -o /chal /src/chal.c

FROM ghcr.io/nocohackers/chal-pwn:2026
COPY --from=build --chmod=755 /chal /srv/chal
ENV CHAL_NAME="Municipal Connectivity Test"

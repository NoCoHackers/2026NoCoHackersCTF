# Build context is the repository root.
FROM golang:1.24-bookworm AS builder
WORKDIR /build
COPY challenges/pwn/boones-trail-guide/src/go.mod ./
COPY challenges/pwn/boones-trail-guide/src/main.go ./
RUN CGO_ENABLED=0 go build -trimpath -o /srv/boone .

FROM ghcr.io/nocohackers/chal-pwn:2026
COPY --from=builder --chmod=755 /srv/boone /srv/boone
COPY --chmod=755 challenges/pwn/boones-trail-guide/src/serve /srv/chal
COPY challenges/pwn/boones-trail-guide/src/trails/ /srv/trails/
ENV CHAL_NAME="Boone's Trail Guide" CHAL_TIMEOUT="180"

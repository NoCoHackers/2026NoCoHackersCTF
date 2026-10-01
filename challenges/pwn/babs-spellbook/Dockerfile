# Build context is the repository root. CGO links against SQLite in the builder.
FROM golang:1.24-bookworm AS builder
WORKDIR /build
COPY challenges/pwn/babs-spellbook/src/go.mod challenges/pwn/babs-spellbook/src/go.sum ./
RUN go mod download
COPY challenges/pwn/babs-spellbook/src/main.go ./
RUN CGO_ENABLED=1 go build -trimpath -o /srv/babs .

FROM ghcr.io/nocohackers/chal-pwn:2026
COPY --from=builder --chmod=755 /srv/babs /srv/babs
COPY --chmod=755 challenges/pwn/babs-spellbook/src/serve /srv/chal
ENV CHAL_NAME="Babs's Spellbook" CHAL_TIMEOUT="180"

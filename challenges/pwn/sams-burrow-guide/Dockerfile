# Build context is the repository root. Each lesson is a small, intentionally
# vulnerable C binary; mitigations are selected to keep its teaching goal clear.
FROM gcc:14-bookworm AS builder
WORKDIR /build
COPY challenges/pwn/sams-burrow-guide/handout/*.c challenges/pwn/sams-burrow-guide/handout/*.h ./
RUN gcc -O0 -fno-stack-protector -no-pie -Wall -Wextra -o /srv/lesson1 lesson1.c \
 && gcc -O0 -fno-stack-protector -no-pie -Wall -Wextra -o /srv/lesson2 lesson2.c \
 && gcc -O0 -fno-stack-protector -no-pie -Wall -Wextra -o /srv/lesson3 lesson3.c \
 && gcc -O0 -fno-stack-protector -no-pie -Wall -Wextra -o /srv/lesson4 lesson4.c

FROM ghcr.io/nocohackers/chal-pwn:2026
COPY --from=builder --chmod=755 /srv/lesson1 /srv/lesson1
COPY --from=builder --chmod=755 /srv/lesson2 /srv/lesson2
COPY --from=builder --chmod=755 /srv/lesson3 /srv/lesson3
COPY --from=builder --chmod=755 /srv/lesson4 /srv/lesson4
COPY --chmod=755 challenges/pwn/sams-burrow-guide/src/serve /srv/chal
ENV CHAL_NAME="Sam's Burrow Guide" CHAL_TIMEOUT="180"

# Main Character Syndrome - author's write-up

**Flags:** primary in `challenge.yml`, release-job flag in `challenge.exec.yml`.

## First flag: provenance

1. Download the sample `cache-de-spectre` ELF (also available from CTFd). The UI shows its digest and a passing CI record for `feature/poudre`.
2. Upload the sample with ordinary JSON metadata, such as `{"description":"Cache de Spectre: preview"}`. Promotion fails; the verifier counts one parsed record. A description consisting only of forged JSON fails the required prose prefix.
3. Put a JSON-escaped newline in the description after the prefix, followed by an object with the uploaded ELF's SHA-256 digest, `source.branch` set to `main`, and `result` set to `passed`. The first `jq -r` decodes `\n` into a real newline; the second `jq -cR 'fromjson? | select(type == "object")'` treats it as another provenance record. The job approves and returns the first flag.

## Second flag: release job

The upload is **not** restricted to the sample ELF. Build an x86-64 static ELF with a `_start` entry point and raw `read`, `write`, and `exit` syscalls. The sample source at `src/cache-de-spectre.c` is a working template. Compile with `gcc -nostdlib -static -no-pie` and compute the digest of the new binary. Forge the same metadata record for *that* digest so the gate approves it. The jailed job gives the program one secret line on stdin; a program that reads fd 0 and writes fd 1 reports the second flag in its captured output.

The binary does not execute before the JSON provenance check. The jail runs it from a memfd because `/tmp` is noexec. The runner installs a seccomp allowlist before execution (read, write, exit, signal return, and the one execveat required to launch it); it passes no environment and closes other file descriptors. The outer container stays unprivileged, read-only, cap-dropped, and egress-filtered. Output, CPU, address space, upload size, and execution time are capped. A normal dynamically linked ELF will not start inside this syscall-only jail.

## Unintended paths you're aware of

A program attempting to open `/proc/1/environ` should be killed by seccomp; `solution/solve-exec.sh` checks this before solving. Both autosolves start against fresh containers and must forge provenance independently. The first stage is a trust-boundary bug, not code execution by jq; the second stage is deliberately executing an approved user ELF with only a controlled input stream.

## Difficulty estimate

First flag: intermediate, about 20-30 minutes. Second flag: intermediate/hard, depending on familiarity with minimal static ELF programs and Linux syscalls.

## Anything the organizers should watch

Production TLS comes from Traefik; local tests use HTTP. The image installs `jq` and receives both flags at runtime. If players stall on the first stage, point to the verifier's parsed-record count. For the second stage, point to the sample ELF source and the syscall restrictions.

# NoCo Hackers CTF 2026

> *Something's loose in Old Town.*

The complete kit for running **NoCo Hackers CTF 2026**, a Halloween-in-Fort-
Collins capture-the-flag event. This repository holds the shared theme, the
base Docker images challenges are built on, the challenges themselves, the CI
that proves every challenge is solvable, and the deploy configuration for the
two hosts the event runs on.

**This repo was private until the event ended.** It contains flags and
solutions in the clear.

## For the impatient

Run the **entire event** on your laptop, including CTFd, Traefik routing, and
every challenge, with one command:

```sh
make dev                # build everything and bring it all up
make dev-urls           # print where to reach it
```

That gives you:

| | |
|---|---|
| `http://ctf.localhost` | the CTFd scoreboard |
| `http://<sub>.chal.localhost` | each web challenge, routed by Traefik exactly as in production |
| `nc localhost 30000…` | each TCP challenge on its assigned port |
| `http://localhost:8081` | the Traefik dashboard |

`make dev-down` stops it (`CLEAN=1` also drops CTFd's database). If your host
resolver doesn't send `*.localhost` to loopback, `make dev-hosts` prints the
`/etc/hosts` lines.

Working on a single challenge instead:

```sh
FLAG='noco{local}' docker compose \
  -f challenges/web/ghostdex/compose.yml up --build   # → localhost:8080
tools/test-challenge.sh challenges/web/ghostdex        # build, boot, autosolve
```

## What's here

| path | what it is |
|------|-----------|
| **`theme/`** | The look of the event. Design tokens (`tokens.css`), components (`theme.css`), header/footer partials, favicon, and the netcat banner. One palette and system-font type stack. Every challenge links `theme.bundle.css`. |
| **`images/`** | The three base images every challenge builds `FROM`: `base-web` (nginx + runtime flag templating), `base-pwn` (socat fork-per-connection), and `theme-assets` (just the theme, for challenges with their own stack). |
| **`challenges/`** | One bundle per directory, grouped by category. `TEMPLATE/` is the starting point. The current tree contains 8 locally runnable bundles, 1 external bundle and 23 independently scored entries. |
| **`deploy/`** | Two hosts. `deploy/scoreboard/` runs CTFd + MariaDB + Redis + Caddy with backups; `deploy/chals/` runs Traefik and every challenge; `deploy/host/` and `deploy/digitalocean/` bootstrap existing VPSes and configure their edge. |
| **`tools/`** | Build, validate, and test scripts, including the same ones CI runs. |
| **`.github/`** | CI, code owners, and the templates for proposing and submitting challenges. |

## Current challenge set

The repository currently has **8 locally runnable bundles and 1 external bundle**
producing **23 scored entries**. External entries remain `hidden` until an
organizer completes explicit live verification. The manifests are the
source of truth; this table is an author-facing snapshot of the current tree.

| category | bundle | scored entries | service |
|----------|--------|---------------:|---------|
| web | `ghostdex` | 1 | HTTP |
| web | `i-25-rampage` | 1 | HTTP |
| web | `slithery-little-snake` | 1 | HTTP |
| pwn | `municipal-connectivity-test` | 1 | TCP `30001` |
| pwn | `babs-spellbook` | 5 | TCP `30002` |
| pwn | `boones-trail-guide` | 4 | TCP `30003` |
| pwn | `sams-burrow-guide` | 4 | TCP `30004` |
| misc | `old-town-accounts` | 3 | Web terminal |
| ai | `meridian-hotline` | 3 | External Azure phone/text service |

The three guided pwn bundles form complementary curricula:

- **Babs's Spellbook** progresses through SQL-injection techniques.
- **Boone's Trail Guide** explores shell, argument, blind, and persisted command
  injection.
- **Sam's Burrow Guide** starts with adjacent-data corruption, advances through
  function-pointer and saved-return-address overwrites, then branches into a
  format-string write. It provides vulnerable C source and a binary-input
  primer, while Sam explains Python little-endian address packing in-dialogue;
  participants still build their own prompt-aware socket client.

Run `tools/validate.py` to validate the current manifests, and `make dev-urls`
for endpoints generated from them. (`tools/validate.py` also validates the
starter bundle under `challenges/TEMPLATE`, so its aggregate count is one
higher than the event snapshot above.)

## How it works, briefly

- **One consistent look.** The theme is a build-time dependency, not a
  guideline: challenges inherit it from the base image and link one stylesheet,
  so 25 challenges from different authors read as one event. Sensible system
  font stacks keep typography fast and network-independent.
- **Challenges are code.** Each codebase/deployment is a directory with a
  primary `challenge.yml`, an automated solve and an organizer writeup. Local
  services also include a Dockerfile and source; external services stay on
  their existing host. A
  directory may add `challenge.<id>.yml` manifests for separately scored flags.
  Metadata syncs into CTFd via `ctfcli`; deploy compose comes from the primary.
- **CI won't let a broken challenge through.** Every pull request builds each
  changed local bundle once, then boots a fresh hardened container for every
  autosolve and asserts its flag comes back. It also fails on image-layer leaks.
  External bundles get offline contract checks in PR CI and require explicitly
  requested live solves before becoming visible; CI does not silently spend a
  provider budget.
- **Flags are injected at runtime.** Source uses `__FLAG__` or a named bundle
  token such as `__FLAG_UART__`; the real flags live only in their manifests
  and reach containers through the environment, never a pullable image.
- **Two hosts, one boundary.** The scoreboard (player credentials, scores) and
  the challenge containers (attacker-controlled code) run on separate VMs on
  separate networks, so a container escape can't reach the scoreboard.

## Submitting a challenge

Challenges come from more than one author, so submission is PR-based and
gated by CI and a category owner's review.

1. **Pitch it:** open a [challenge proposal](.github/ISSUE_TEMPLATE/challenge-proposal.yml)
   so two people don't build the same thing.
2. **Build it:** `cp -r challenges/TEMPLATE challenges/<category>/<slug>`,
   fill in `challenge.yml`, write the challenge, and write a **real**
   `solution/solve.sh` and `solution/writeup.md`.
3. **Check it:** `tools/validate.py` and `tools/test-challenge.sh` must pass
   locally; they're what CI runs.
4. **Open a PR:** the checklist in the PR template is the definition of done.

Full contributor guidance is in **[AGENTS.md](AGENTS.md)**.

## Documentation

- **[AGENTS.md](AGENTS.md):** the working contract: how to add a challenge,
  the `challenge.yml` schema, flag handling, the base images, house style.
  Read this before changing anything.
- **[INFRASTRUCTURE.md](INFRASTRUCTURE.md):** the two-host layout, domains and
  TLS, the isolation model, deployment, backups, and the event-day runbook.

## The event

- **Theme:** Halloween in Fort Collins: Old Town, the Poudre, Horsetooth,
  aspen gold, pumpkin light. Challenge descriptions are written in-world;
  challenges are places something got loose.
- **Scoreboard:** CTFd at `ctf.nocohackers.com`.
- **Categories:** web, pwn, rev, crypto, forensics, osint, misc, ai.
- **Participation:** individual players (CTFd *users* mode).
- **Flag format:** `noco{...}`.

## Credits

Run by NoCo Hackers, Fort Collins, Colorado. Challenges by the community;
infrastructure and theme maintained by the organizing team.

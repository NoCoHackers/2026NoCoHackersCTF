# AGENTS.md

Working notes for anyone — human or AI coding agent — making changes in this
repository. This is the operational contract; `README.md` is the friendly
overview and `INFRASTRUCTURE.md` is the deployment reference. Read this before
you touch anything, and keep changes consistent with it.

## What this repository is

Everything needed to run **NoCo Hackers CTF 2026** ("Something's loose in Old
Town" — Halloween in Fort Collins): the shared visual theme, the base Docker
images challenges build on, every challenge, the CI that proves challenges
work, and the deploy configuration for two hosts.

The repository is **private until the event ends**. Flags, solutions, and
unreleased challenges are all here in the clear. Do not fork it public, do not
paste challenge internals into a public issue, and do not push challenge images
to a public registry before kickoff.

## Golden rules

1. **A challenge that doesn't autosolve in CI does not ship.** Every runnable
   challenge carries `solution/solve.sh`, and CI builds it, boots it, and runs
   that script against it on every pull request. No exceptions, including "it's
   just a static file" — those still get a solve that fetches the file.
2. **Flags live in challenge manifests and nowhere else in the source tree.**
   The primary is `challenge.yml`; separately scored bundle entries use
   `challenge.<id>.yml`. Source uses runtime flag tokens rather than literals. A flag
   baked into an image layer is readable by anyone who can pull the image, so
   CI fails the build if it finds one. See *Flag handling* below.
3. **Never weaken the container hardening.** `read_only`, `cap_drop: ALL`,
   `no-new-privileges`, and the resource caps are how one compromised challenge
   stays one compromised challenge. Authors may *raise* resource ceilings in
   `challenge.yml`; nobody opts out of the security options.
4. **The generated compose is generated.** `deploy/chals/docker-compose.generated.yml`
   is produced from the challenges by `deploy/chals/generate.py`. Change a
   `challenge.yml`, then re-run the generator; never hand-edit the output. CI
   fails if it's stale.
5. **Match the surroundings.** New code should read like the code next to it —
   same shell idioms, same comment density, same naming. New challenges should
   look like the same event: link the shared theme, write descriptions in its
   voice.

## Repository map

```
theme/          Design tokens, component CSS, partials, favicon, banner.
                Edit tokens.css / theme.css; theme.bundle.css is generated.
images/         Docker images. The three challenge base images:
                  theme-assets  just the theme, for FROM-in-a-stage use
                  base-web      nginx, SSI partials, runtime flag templating
                  base-pwn      socat fork-per-connection, drops to `ctf` user
                plus caddy/     the scoreboard's Caddy + rate_limit module
challenges/     One codebase/deployment bundle per directory under its category.
                A bundle may contain multiple scored manifests. TEMPLATE/ is
                the starting point; copy it.
deploy/chals/   Challenge host: Traefik + the generated compose + a Makefile.
deploy/scoreboard/  Scoreboard host: CTFd + MariaDB + Redis + Caddy + backups.
deploy/host/    Role-based bootstrap and artifact-only remote deployment.
deploy/digitalocean/  Cloud Firewall and DNS automation for existing Droplets.
tools/          Build, validate, and test scripts. Start here to understand CI.
.github/        CI workflow, CODEOWNERS, PR and proposal templates.
```

## Adding a challenge

```sh
cp -r challenges/TEMPLATE challenges/<category>/<slug>
$EDITOR challenges/<category>/<slug>/challenge.yml     # metadata + x-noco deploy block
# build your challenge under src/, write the real solve and writeup
FLAG='noco{local}' docker compose -f challenges/<category>/<slug>/compose.yml up --build
tools/validate.py challenges/<category>/<slug>          # schema + collision checks
tools/test-challenge.sh challenges/<category>/<slug>    # build, boot, autosolve
deploy/chals/generate.py                                # refresh the deploy compose
```

Then open a PR. A category owner who didn't write it reviews it (see
`.github/CODEOWNERS`). The PR template's checklist is the definition of done.

`<category>` is one of: `web pwn rev crypto forensics osint misc`. The
directory must live under its declared category — the validator enforces it.

A single codebase may expose multiple independently scored entries. Keep the
primary deployment in `challenge.yml` and add complete ctfcli manifests named
`challenge.<id>.yml`, where `<id>` is lowercase kebab-case and `main` is
reserved. Supplemental `x-noco` blocks may only set `autosolve`; they inherit
the primary service, endpoint, and resource limits. See `challenges/TEMPLATE/README.md`.

### The `challenge.yml` contract

The top-level keys are ctfcli's schema and sync straight into CTFd. The
`x-noco:` block is ours and drives deployment. Both are validated. The fields
that matter most:

| field | why it matters |
|-------|----------------|
| `flags` | Exactly one real flag per scored manifest. Must match `noco{...}` and be unique across the event. |
| `x-noco.kind` | `web` (gets a subdomain), `tcp` (gets a port), or `static` (handout only, nothing runs). |
| `x-noco.subdomain` | web only; globally unique; becomes `<sub>.chal.nocohackers.com`. |
| `x-noco.port` | tcp only; unique; in `30000–30099`. |
| `x-noco.autosolve` | Path to the script CI runs. Must exit 0 and print the flag. |
| `x-noco.memory` / `cpus` / `pids` | Resource ceilings. Ask for what you need; the defaults suit anything that isn't a database. |
| `state` | Authors leave it `hidden`. Organizers flip it to `visible` at kickoff. |

### Fixed-point scoring

The event uses fixed scoring. Every scored manifest sets `type: standard` and
must not contain a dynamic-scoring `extra` block (`initial`, `decay`, or
`minimum`). Choose `value` from these event-wide tiers:

| value | tier | expected solve |
|------:|------|----------------|
| `100` | beginner | Direct, strongly guided, or one obvious vulnerability; little or no automation. |
| `200` | easy | One familiar technique with modest inspection, context handling, or scripting. |
| `300` | medium | Multiple steps, a less familiar primitive, or binary/protocol scripting. |
| `400` | hard | Blind inference, substantial automation, deeper exploitation, or niche-system investigation. |
| `500` | expert | A long, specialized, multi-stage chain requiring several independent insights. |

Rate difficulty against the whole event, not only neighboring lessons in a
bundle. Lesson numbers do not require increasing values: a later guided side
path may be easier than an earlier blind or automation-heavy lesson. Revisit the
value whenever hints, handouts, or the intended exploit path materially change.

## Flag handling

This is the single most important mechanic in the repo, so it's spelled out.

- Each real flag is written **once**, under `flags:` in its `challenge.yml` or
  `challenge.<id>.yml` manifest.
- In challenge source, use `__FLAG__` for the primary or `__FLAG_<ID>__` for a
  bundle entry. Runtime environment equivalents are `FLAG` and
  `NOCO_FLAG_<ID>` (kebab-case ids become underscores).
- `base-web` renders `/srv/app` into a tmpfs at boot, substituting those flag
  tokens (and `{{CHAL_NAME}}`, `{{CHAL_CATEGORY}}`) from environment variables.
  Flags never touch an image layer.
- `base-pwn` writes the primary to `/flag/flag.txt` and named bundle flags to
  `/flag/<id>.txt`, root-owned and readable by the `ctf` user.
- On the host, `deploy/chals/flags.env` is generated from the challenge
  manifests during deployment, synced as a mode-600 artifact, and kept out of
  git by `.gitignore`. The manifests are the single source of truth.
- CI enforces all of this: `tools/validate.py` fails if a flag literal appears
  anywhere in the source outside `challenge.yml`, and `tools/test-challenge.sh`
  greps the built image's filesystem and history for the flag.

If you find yourself wanting to put a flag directly in source, use its runtime
flag token instead. Always.

## The base images

Build them before building any challenge locally:

```sh
tools/build-base-images.sh      # tags ghcr.io/nocohackers/chal-{theme,web,pwn}:2026
```

- **base-web** — `FROM ghcr.io/nocohackers/chal-web:2026`, `COPY` your static
  site into `/srv/app`, set `CHAL_NAME`/`CHAL_CATEGORY`. You get the theme at
  `/theme`, SSI header/footer partials, a `/healthz` endpoint, a CSP that
  forbids CDN calls, and runtime flag templating. Runs unprivileged on `:8080`.
- **base-pwn** — `FROM ghcr.io/nocohackers/chal-pwn:2026`, `COPY --chmod=755`
  your binary to `/srv/chal`, set `CHAL_NAME`. socat forks one process per
  connection as the unprivileged `ctf` user, so a crash or corruption is
  confined to that one player's session. Listens on `:1337`.
- **base-theme** — nothing but the theme, for challenges that need their own
  stack: `COPY --from=ghcr.io/nocohackers/chal-theme:2026 /theme ...`.

Because the images inject the flag and enforce hardening, **every challenge
build context is the repository root**, not the challenge directory — that's
how the Dockerfile reaches `theme/`. The `Dockerfile` and `compose.yml` in
`TEMPLATE/` already do this correctly; copy them.

## No outbound network from challenges

The challenge host egress-filters container traffic. A challenge that fetches a
font, a script, or an API from the public internet at request time will hang.
Vendor everything. The theme uses system font stacks and the base-web CSP is
`default-src 'self'`. If a challenge genuinely needs to reach something, say so
in the proposal — it's an infrastructure decision, not a per-challenge one.

## Pushing to CTFd (challenges + event config, without touching scores)

CTFd is updated over its API, not by hand and not by the destructive
export/import backup. Two things get pushed; **neither touches users, teams,
submissions, or scores**:

- **Challenges** - created if new, updated in place if they already exist.
- **Event config** - name/description/theme from `event.yml`.

```sh
export CTFCLI_ACCESS_TOKEN=ctfd_xxx      # CTFd -> Settings -> Access Tokens (admin)
make sync                                # push to production (url from .ctf/config)
make sync TARGET=dev                     # push to the local `make dev` stack
deploy/scoreboard/sync.sh --dry-run      # show the config diff, write nothing
deploy/scoreboard/sync.sh -c challenges/web/ghostdex   # a single challenge
```

Under the hood `sync` runs `ctf challenge install --force` per challenge (create
-or-update, matched by name) and `tools/ctfd-config.py` for `event.yml`. The
token is read from the environment and never committed; `.ctf/config` holds only
the public URL.

On every successful `main` push, CI validates and autosolves, publishes images,
deploys the challenge host, verifies its public edge, then runs `make sync`.
The deploy job temporarily allows only its runner's `/32` through the
DigitalOcean SSH firewall and removes that rule afterward. Configure the GitHub
`production` environment with variables `CHALLENGE_HOST` and
`CHALLENGE_FIREWALL_ID`, plus secrets `CHALLENGE_SSH_PRIVATE_KEY`,
`CHALLENGE_SSH_KNOWN_HOSTS`, `DIGITALOCEAN_ACCESS_TOKEN`, and
`CTFCLI_ACCESS_TOKEN`. Use a dedicated deploy SSH key and a DigitalOcean token
limited to firewall access. Protect `main`: code merged there can reach the
Docker-owning deploy account and is therefore trusted production code.

**Participation mode.** `event.yml`'s `mode:` is `users` (individual players)
or `teams`. It's a launch-time choice, not a live knob: `tools/ctfd-bootstrap.py`
sets it at setup, and `make sync` will set it on a still-empty instance but
**refuses** to change it once any participant exists (flipping modes after people
have scored regroups or orphans their scores). Decide it before the event opens.
The event is configured for `users`.

**The rename trap.** CTFd matches challenges by **name**. Rename a published
challenge and the next sync creates a *second* challenge and splits its solves -
it does not rename the existing one. `challenges/names.lock` records the name
each directory published under, and `tools/validate.py` fails on an unblessed
rename. When a rename is intentional, bless it with `tools/lock-names.py` (and
rename it in the CTFd admin UI yourself, so solves follow). Treat a challenge's
`name` as its stable identity once the event is live.

**Version pairing.** ctfcli and CTFd move together - ctfcli >= 0.1.7 calls an
endpoint that only exists in CTFd >= 3.8. We pin CTFd 3.7.7 and ctfcli 0.1.6 in
`deploy/scoreboard/requirements-sync.txt`; re-check that pairing if you bump
either. First-time setup / a dev admin token: `tools/ctfd-bootstrap.py --dev`.

## Running the whole environment locally

`make dev` stands up the complete event on your machine — CTFd, Traefik, and
every challenge — from source, with no registry, no secrets, and no ACME. It
generates a local compose (`deploy/dev/`), builds each challenge, and routes
web challenges at `<sub>.chal.localhost`, the scoreboard at `ctf.localhost`,
and TCP challenges on their assigned ports. `make dev-urls` lists them;
`make dev-down` tears it down.

Dev differs from production in exactly three ways, all in `deploy/chals/generate.py`:
images are **built** not pulled, the domain is `*.localhost` not
`*.chal.nocohackers.com`, and there's **no TLS**. Dev also drives Traefik from a
generated file-provider route table rather than the Docker provider, so it
doesn't depend on the Docker daemon's API version (some newer daemons reject
Traefik's default). Everything else — the hardening, the ports, the network
isolation, the runtime flag injection — is identical, so a challenge that works
under `make dev` works when deployed.

## Testing your work

| command | what it checks |
|---------|----------------|
| `tools/validate.py [dir]` | Bundle and manifest schema; flag format; subdomain/port/flag/name collisions; flags not leaked into source. |
| `tools/test-challenge.sh <dir>` | Builds once, scans every flag, then uses a fresh hardened container for each autosolve. Static bundles run their solves without a container. Set `NOCO_KEEP=1` to leave containers up. |
| `tools/build-base-images.sh` | Rebuilds the three base images. |
| `sh tools/build-theme.sh` | Regenerates `theme/theme.bundle.css`. Run it after editing tokens or components; CI fails if the bundle is stale. |

CI (`.github/workflows/ci.yml`) runs validate on everything, then autosolve on
the challenges your PR actually changed (or all of them, if you touched the
theme, a base image, or the tooling). On merge to `main` it pushes the base and
challenge images to GHCR.

## Style

- **Shell**: `set -euo pipefail` in bash, `set -eu` in POSIX sh. Quote
  expansions. Fail loudly with a message a tired organizer can act on at 2am —
  every `FATAL` in the entrypoints names the fix, not just the problem.
- **Python**: standard library plus PyYAML only. No framework, no clever
  metaprogramming — these scripts get read more than they get run.
- **Comments** explain *why*, since the *what* is usually plain. Match the
  density already in the file.
- **The flag format is `noco{...}`.** Lowercase prefix, curly braces. The
  validator enforces it; don't invent variants.

## When something breaks during the event

`INFRASTRUCTURE.md` has the runbook. The short version: challenges are
disposable and independently restartable (`make -C deploy/chals restart
S=<service>`); the scoreboard is not, so it lives on its own host and gets
backed up hourly. One organizer owns the scoreboard and isn't writing or
solving challenges during the event.

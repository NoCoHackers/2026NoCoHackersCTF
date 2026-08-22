# INFRASTRUCTURE.md

How NoCo Hackers CTF 2026 is hosted: the two-host layout, the domains, the
security boundaries, and the runbook for the day. If you're adding a challenge,
you want `AGENTS.md`; this document is for whoever stands the event up and keeps
it running.

## Design in one paragraph

Two cheap cloud VMs. One runs **CTFd and only CTFd** — the scoreboard, every
player's password hash, the thing that must not fall over. The other runs
**every challenge container** — code submitted by many people, some of which
players will actively try to break out of. The two are separate hosts, on
separate networks, precisely so that a container escape on the challenge host
cannot reach the scoreboard's database. That single boundary is the most
important decision in this file; everything else is detail.

Sized for a local meetup: roughly 50 players, ~25 challenges.

## The two hosts

```
                         Internet
                            │
        ┌───────────────────┴────────────────────┐
        │                                         │
   ┌────▼─────────────────┐             ┌─────────▼──────────────────────┐
   │  scoreboard  (VM A)  │             │      chals  (VM B)             │
   │  2 vCPU / 4 GB       │             │      4 vCPU / 8 GB             │
   │                      │             │                                │
   │  Caddy ── CTFd       │             │  Traefik ─┬─ web-*  :8080      │
   │            │  │      │             │           │  (per subdomain)   │
   │        MariaDB Redis │             │           └─ ...               │
   │        (internal net)│             │  published ports ─ tcp-* :1337 │
   │                      │             │           (30000–30099)        │
   │  nightly/hourly      │             │  egress-filtered: no outbound  │
   │  backups off-host    │             │  from challenge containers     │
   └──────────────────────┘             └────────────────────────────────┘
      ctf.nocohackers.com                  *.chal.nocohackers.com
      (apex = your main site)             chal.nocohackers.com:30000-30099
```

Hetzner is the value pick (a CPX21 and a CPX41 come to roughly $15–20/month for
the event window); DigitalOcean or Linode work identically. Prices drift —
re-check before you commit.

### Why two hosts and not one

Challenge containers run other people's code and are a deliberate target. CTFd
holds credentials and the scoreboard. Colocating them means a single container
escape — or an SSRF that reaches the Docker socket, or a shared-kernel
0-day — turns "one challenge is owned" into "the whole event is owned,
including password hashes." Two hosts on isolated networks make that a boundary
an attacker has to cross, not a step they get for free. For the price of a
second small VM, it's not close.

## Domains

One registered domain, `nocohackers.com`, with subdomains:

| name | host | serves |
|------|------|--------|
| `nocohackers.com`, `www` | **your main site** | Not served by the CTF - left pointed at your existing website. |
| `ctf.nocohackers.com` | scoreboard | CTFd - the scoreboard **and** the CTF's public front page. |
| `*.chal.nocohackers.com` | chals | Web challenges, one subdomain each, routed by Traefik. |
| `up.chal.nocohackers.com` | chals | Traefik health/whoami; also the router that pins the wildcard cert. |
| `chal.nocohackers.com:30000–30099` | chals | Raw-TCP challenges (pwn/misc). |

### Where domains are configured

Every hostname derives from one block in **`event.yml`**:

```yaml
domain:
  base: nocohackers.com      # the registered domain
  scoreboard: ctf            # scoreboard at ctf.<base>
  challenges: chal           # web challenges at *.chal.<base>
  acme_email: organizers@nocohackers.com
  dns_provider: digitalocean # Traefik DNS-01 provider for the wildcard
```

Run `make domains` after editing it. That regenerates `deploy/domains.env` (the
`NOCO_*` vars) and the challenge route table. From there:

- **Challenge subdomains** - `deploy/chals/generate.py` reads the block directly.
- **Traefik edge** (`compose.traefik.yml`) - interpolates `${NOCO_*}` from
  `deploy/domains.env` (passed via `--env-file`).
- **Caddy scoreboard** (`Caddyfile`) - reads `{$NOCO_*}` from the same env file.
- **`make sync`** - derives the CTFd URL from the block.

`tools/domains.py --print` shows the derived hostnames; `--check` (run in CI)
fails if `deploy/domains.env` is stale. Hostnames written as prose in challenge
descriptions and theme links aren't generated - a
`tools/validate.py` warning flags any that fall outside the configured domain
after a rebrand.

### TLS

- **Scoreboard** uses Caddy with automatic HTTP-01 — single fixed hostnames,
  nothing to configure.
- **Challenge host** uses Traefik with a **wildcard** cert for
  `*.chal.nocohackers.com`, obtained via **DNS-01** (DigitalOcean provider,
  set by `domain.dns_provider` in event.yml; the API token goes in
  `deploy/chals/dns.env` as `DO_AUTH_TOKEN`). DNS-01 is required because
  HTTP-01 cannot issue wildcards, and a wildcard is what lets a new challenge
  appear at its own subdomain without provisioning a per-host certificate.

Point DNS at the hosts (the domain's nameservers are DigitalOcean), and both
hosts get certificates automatically once the DNS-01 token is in place.

### DNS records to create

Created on the `nocohackers.com` zone in DigitalOcean. **Leave the existing
apex (`@`) and `www` records alone — those point at the main website; the CTF
never touches them.** Add only:

| Type | Name (host) | Value | Purpose |
|------|-------------|-------|---------|
| `A` | `ctf` | scoreboard host IPv4 | CTFd (scoreboard + landing) at `ctf.nocohackers.com` |
| `A` | `*.chal` | challenge host IPv4 | wildcard for every web challenge (`<name>.chal.nocohackers.com`) |
| `A` | `up.chal` | challenge host IPv4 | Traefik health / cert-pin router (`up.chal.nocohackers.com`); the wildcard also covers it, but an explicit record is harmless |
| `A` | `chal` | challenge host IPv4 | the single host players `nc` into for raw-TCP challenges (`chal.nocohackers.com:<port>`); the `*.chal` wildcard does **not** cover this bare label, so it needs its own record |

Notes:

- Add matching `AAAA` records if the hosts have IPv6.
- The `*.chal` wildcard is what lets a new web challenge appear at its own
  subdomain with no DNS change — you never add a record per challenge.
- **Raw-TCP challenges all share the `chal` host**, differing only by port
  (`chal.nocohackers.com:30000`, `:30001`, …). That's the one reason the bare
  `chal` record above exists — the `*.chal` wildcard covers `<name>.chal` but
  not `chal` itself. No per-challenge TCP record is ever needed.
- The **DNS-01 token** in `deploy/chals/dns.env` (`DO_AUTH_TOKEN`) must have
  write access to the `nocohackers.com` zone, so Traefik/lego can create the
  temporary `_acme-challenge.chal.nocohackers.com` TXT records when it issues
  and renews the wildcard certificate. No TXT records are created by hand.
- All of these hostnames derive from `event.yml`'s `domain:` block; if you
  change the base or subdomains there, re-derive with `tools/domains.py --print`
  to get the exact names to create.

> **Docker API version.** Traefik's Docker provider speaks an older Docker API
> version by default. A normal VPS daemon accepts it; a very new daemon (min API
> ≥ 1.40) may reject it with *"client version 1.24 is too old."* If you hit that
> on the prod host, set `DOCKER_API_VERSION` on the Traefik service (already
> stubbed in `compose.traefik.yml`) to a version in the daemon's range, or lower
> the daemon's `min-api-version`. Local dev sidesteps this entirely by using
> Traefik's file provider — see AGENTS.md, "Running the whole environment locally."

### Why TCP challenges don't get subdomains

SNI — the mechanism that lets many HTTPS hostnames share one IP and port — only
exists inside TLS. A `nc`-style pwn challenge speaks raw bytes with no TLS and
no hostname, so there is nothing to route on. Those challenges get a real,
unique published port instead. The block is `30000–30099`; `x-noco.port`
assigns one and `tools/validate.py` rejects collisions.

## Isolation, layer by layer

- **Host boundary** — challenges and the scoreboard are different VMs. The
  challenge host's firewall allows inbound `80/443` and `30000–30099` and
  nothing else; egress from challenge containers to the scoreboard's address is
  denied.
- **No container egress** — challenge containers can't reach the public
  internet, so a challenge can't call home, exfiltrate, or depend on a CDN that
  might vanish. Vendor assets; the theme uses system font stacks.
- **Per-container hardening** — applied to every challenge by
  `deploy/chals/generate.py`, not left to authors:
  `read_only: true`, `cap_drop: ALL`, `no-new-privileges`, a `pids_limit`, a
  `mem_limit`, and a `cpus` cap. Writable state goes on small tmpfs mounts
  (`/tmp`, plus `/srv/www` for web or `/flag` for pwn). The pwn image adds back
  only `SETUID`/`SETGID`/`SETPCAP`, which socat needs to drop from root to the
  unprivileged `ctf` user per connection.
- **Network segmentation on the challenge host** — web challenges sit on the
  `noco-edge` network with Traefik. TCP challenges sit on an `isolated`
  network with no route to the web challenges or to each other. A player who
  owns one challenge finds nothing else reachable.

## Per-player instances (and why we mostly don't)

At 50 players, deploying per-team instancing (ctfd-whale needs Docker Swarm +
frp; klodd needs Kubernetes) would add the most fragile component in the stack
to serve the smallest slice of the event. We solve the underlying need a tier
down instead:

- **Fork-per-connection** (the `base-pwn` default) gives every TCP connection a
  fresh process as the `ctf` user on a read-only rootfs. A player who crashes
  or corrupts the binary affects only their own connection. This covers the
  three things people actually want instancing for — crashes, state
  corruption, and "someone left a backdoor."
- **Stateless web challenges** — if a web challenge is read-only or resets its
  own state per request, shared hosting is fine, and almost all of them are.
- **The rare genuinely-stateful challenge** — a service a player reconfigures
  and must hold — gets 4–5 static numbered copies on different subdomains, with
  teams assigned to one. Zero new infrastructure.

Revisit true instancing only if the event ends up with five or more inherently
stateful challenges. It won't, at this scale.

## Deploying

### Challenge host

```sh
# one time
make -C deploy/chals init          # creates the shared noco-edge network
cp deploy/chals/dns.env.example deploy/chals/dns.env   # then add your DO_AUTH_TOKEN

# each deploy
deploy/chals/generate.py           # refresh compose from challenges/ (usually already committed)
make -C deploy/chals up            # decrypt flags, pull images, start everything
make -C deploy/chals ps            # confirm everything is healthy
```

Images are built and pushed by CI on merge to `main` and deployed **by tag**
(`:2026`). Flags come from `flags.env`, decrypted on the host from the
sops/age-encrypted `flags.enc.env`; the plaintext is never committed.

### Scoreboard host

```sh
cd deploy/scoreboard
cp .env.example .env               # set CTFD_SECRET_KEY, MYSQL_* (see below)
docker compose up -d --build       # --build compiles the custom Caddy image
```

The scoreboard's Caddy is a **custom image** (`images/caddy/`): stock Caddy plus
the `rate_limit` module, which the stock image lacks and which the Caddyfile
needs to cap `/login`, `/register`, and flag submissions at the edge. `--build`
compiles it locally; CI also publishes it to `ghcr.io/nocohackers/caddy-ratelimit`.

Generate the secrets with `openssl rand -hex 32` (for `CTFD_SECRET_KEY`) and
`openssl rand -hex 20` (for the DB passwords). Redis-backed sessions are on by
default via `REDIS_URL` — turn that on *before* the event, not during it, or
active sessions drop when you switch.

Before players arrive: fork the CTFd theme (`deploy/scoreboard/themes/README.md`)
so the scoreboard matches the challenges, decide dynamic-vs-static scoring, and
set the rate limits (already configured in the `Caddyfile` for `/login`,
`/register`, and flag submission).

## Updating challenges and config mid-event

The scoreboard is updated through CTFd's API, so challenge fixes and config
tweaks never disturb players. From a checkout with an admin token:

```sh
export CTFCLI_ACCESS_TOKEN=ctfd_xxx     # CTFd -> Settings -> Access Tokens
make sync                                # challenges (create/update by name) + event.yml
```

This create-or-updates every challenge by name and pushes `event.yml`
(name/description/theme, and the participation `mode`). It does **not** touch users, teams, submissions, or
scores - verified against a live instance: participant data and a score record
survived repeated syncs while a challenge's point value updated in place.

Do **not** use CTFd's admin Export/Import to push updates - that snapshot
replaces the whole instance, players included. It's a backup tool (below), not a
deploy tool.

The event runs in **users** mode (individual participants), set in `event.yml`
and applied at setup. `user_mode` is a launch-time decision - `make sync` sets it
on a fresh instance but refuses to change it once participants exist, so choose
it before opening.

Renaming a live challenge is the other sharp edge: CTFd keys on name, so a rename
creates a new challenge and splits solves. `tools/validate.py` blocks an
unblessed rename; see AGENTS.md.

## Backups

The scoreboard is the one piece that can't be recreated from git, so it's the
one piece that gets backed up.

```sh
# hourly during the event, daily otherwise (cron on the scoreboard host):
0 * * * * /opt/noco/deploy/scoreboard/backup.sh >> /var/log/noco-backup.log 2>&1
```

`backup.sh` dumps MariaDB and the uploads volume, keeps the last 48 locally,
and pushes off-host if `NOCO_BACKUP_REMOTE` is set (an rclone remote). **Set
it.** A backup that lives only on the box you're restoring is not a backup.
Practice `restore.sh` against a throwaway host once before the event — an
untested restore is a hope, not a plan.

Challenges need no backup: they're rebuilt from git and carry no player state.

## Event-day runbook

**One organizer owns the scoreboard** and is not writing or solving challenges
during the event. This does not rotate.

Common operations, all from the challenge host:

```sh
make -C deploy/chals ps                       # health of every challenge
make -C deploy/chals logs S=web-haunted-brewery   # tail one challenge
make -C deploy/chals restart S=pwn-cellar-door    # bounce one challenge
make -C deploy/chals reset-one S=web-foo           # nuke + recreate one (drops its tmpfs state)
```

Symptom → action:

| symptom | first move |
|---------|-----------|
| One challenge is down or wedged | `restart` it; if it stays bad, `reset-one`; if still bad, pull the challenge (`state: hidden` in CTFd) and ping the author. |
| A challenge is eating the host | Its `mem_limit`/`pids_limit` should contain it; if an author set them too high, lower in `challenge.yml`, regenerate, `up`. |
| A popular web challenge is slow under load | It's shared and stateless, so it's safe to scale — raise its `cpus`, or run a second copy on another subdomain. |
| Scoreboard slow | Check Redis is up; check the Caddy rate limits are catching a flood on `/login` or flag submission; the DB is on an internal network so it isn't external load. |
| Flag disputes / "my flag isn't accepted" | Compare against `challenge.yml`; the flag there is authoritative and is what CI verified. |
| Suspected compromise of a challenge | Expected and contained — the container is disposable and isolated. `reset-one`. If the *host* looks touched, that's the boundary that matters: rotate, and note the scoreboard is a separate host. |

## Pre-event checklist

- [ ] Two VMs provisioned; challenge-host firewall limited to `80/443` +
      `30000–30099`; egress to the scoreboard denied.
- [ ] DNS pointed; domain on an ACME-capable provider; wildcard cert issued
      (hit `https://up.chal.nocohackers.com`).
- [ ] CTFd up, themed, scoring decided, rate limits on, Redis sessions on.
- [ ] Backups running hourly **and pushing off-host**; a restore rehearsed.
- [ ] Full dry run: deploy everything from a clean clone, and have an organizer
      who didn't write them solve five challenges at random.
- [ ] Every challenge green in CI; `state: hidden` until kickoff.
- [ ] Scoreboard owner named.

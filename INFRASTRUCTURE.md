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

The production automation supports existing DigitalOcean Droplets directly.
Other VPS providers still work with the host bootstrap, but their firewall and
DNS must be configured separately. Prices drift — re-check before you commit.
A first Droplet is one role, not a reason to collapse the boundary: provision
the second before production traffic arrives.

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

The parent `nocohackers.com` zone stays at the registrar. It delegates only
`ctf.nocohackers.com` and `chal.nocohackers.com` to DigitalOcean, leaving the
main website's apex and `www` untouched. Both hosts get certificates
automatically after delegation propagates and the DNS-01 token is installed.

### DNS records to create

At the parent DNS provider, create three `NS` records for each child label:

| Name | Values |
|------|--------|
| `ctf` | `ns1.digitalocean.com`, `ns2.digitalocean.com`, `ns3.digitalocean.com` |
| `chal` | `ns1.digitalocean.com`, `ns2.digitalocean.com`, `ns3.digitalocean.com` |

Do not replace the parent domain's nameservers or manually add an SOA record;
DigitalOcean serves the child zones' SOA after the NS delegation is live.
The automation creates these records inside the DigitalOcean child zones:

| Zone | Type | Name | Value | Purpose |
|------|------|------|-------|---------|
| `ctf.nocohackers.com` | `A` | `@` | scoreboard host IPv4 | CTFd scoreboard and landing page |
| `chal.nocohackers.com` | `A` | `@` | challenge host IPv4 | shared raw-TCP hostname |
| `chal.nocohackers.com` | `A` | `*` | challenge host IPv4 | every web challenge |
| `chal.nocohackers.com` | `A` | `up` | challenge host IPv4 | Traefik health and cert-pin router |

Notes:

- Add matching `AAAA` records if the hosts have IPv6.
- The `*.chal` wildcard is what lets a new web challenge appear at its own
  subdomain with no DNS change — you never add a record per challenge.
- **Raw-TCP challenges all share the `chal` host**, differing only by port
  (`chal.nocohackers.com:30000`, `:30001`, …). That's the one reason the bare
  `chal` record above exists — the `*.chal` wildcard covers `<name>.chal` but
  not `chal` itself. No per-challenge TCP record is ever needed.
- The **DNS-01 token** in `deploy/chals/dns.env` (`DO_AUTH_TOKEN`) must have
  write access to the `chal.nocohackers.com` DigitalOcean zone, so Traefik/lego
  can create temporary `_acme-challenge.chal.nocohackers.com` TXT records when
  it issues and renews the wildcard certificate. No TXT records are created by
  hand.
- All of these hostnames derive from `event.yml`'s `domain:` block; if you
  change the base or subdomains there, re-derive with `tools/domains.py --print`
  to get the exact names to create.

> **Docker API version.** Docker Engine 29 rejects clients fixed to API 1.24.
> Traefik is pinned to v3.6.7 because v3.6.1+ negotiates the daemon API instead
> of hard-coding that old version. Do not downgrade it without testing against
> the production daemon. Local dev sidesteps this dependency by using Traefik's
> file provider — see AGENTS.md, "Running the whole environment locally."

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
- **No container egress** — web challenges live on the internal `noco-edge`
  bridge; only dual-homed Traefik joins its separate egress bridge. Published
  TCP challenges live on fixed `172.31.0.0/24`; bridge ICC is disabled to stop
  lateral traffic, while a persistent `DOCKER-USER` rule drops new outbound
  connections but permits replies to inbound players. Challenge containers therefore can't call home,
  exfiltrate, or depend on a CDN that might vanish. Vendor assets; the theme
  uses system font stacks.
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

### Bootstrap an existing DigitalOcean Droplet

Run provider configuration from an operator machine with authenticated `doctl`.
Restrict SSH to the organizer's current address or VPN; never silently expose it
to the world.

```sh
export NOCO_SSH_CIDR=198.51.100.24/32
make do-configure ROLE=chals DROPLET_ID=123456789 IPV4=203.0.113.10
make host-bootstrap ROLE=chals HOST=root@203.0.113.10
make host-sync ROLE=chals HOST=noco@203.0.113.10
```

Repeat with `ROLE=scoreboard` for the second Droplet. `do-configure` attaches the
role's Cloud Firewall and, when DigitalOcean hosts the zone, upserts only the
CTF DNS records; it never touches the apex or `www`. If the zone is elsewhere,
it warns and leaves DNS unchanged. `host-bootstrap` installs Docker/Compose and role dependencies,
creates the unprivileged `noco` operator, and installs the challenge-container
egress policy where applicable. Details and secret paths are in
`deploy/host/README.md` and `deploy/digitalocean/README.md`.

### Challenge host

Before the first start, place `dns.env` and a read-only GHCR credential as
described in `deploy/host/README.md`. Images are private before
the event, so an unauthenticated `docker compose pull` is expected to fail.
Then deploy from the operator checkout:

```sh
make host-up ROLE=chals HOST=noco@203.0.113.10
ssh noco@203.0.113.10 'make -C /opt/noco/deploy/chals ps'
```

Images are built and pushed by CI on merge to `main` and deployed **by tag**
(`:2026`). The operator checkout generates `deploy/chals/flags.env` directly
from the challenge manifests during deployment, then syncs that mode-600 file
to the host. It remains gitignored; the host receives only deploy artifacts,
not challenge sources or solutions.

### Scoreboard host

Generate and install the scoreboard `.env`, then converge it:

```sh
make host-sync ROLE=scoreboard HOST=noco@203.0.113.20
scp deploy/scoreboard/.env.example noco@203.0.113.20:/opt/noco/deploy/scoreboard/.env
# Replace every placeholder in the remote file with generated secrets.
make host-up ROLE=scoreboard HOST=noco@203.0.113.20
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
(name/description/theme, and the participation `mode`). It does **not** touch
users, teams, submissions, or scores - verified against a live instance:
participant data and a score record survived repeated syncs while a challenge's
point value updated in place.

After every successful `main` push, CI publishes images, temporarily opens SSH
from that runner's `/32`, runs the same artifact-only `host-up` deployment,
checks the public challenge edge, closes SSH again, and only then syncs CTFd.
Configure the GitHub `production` environment as documented in
`deploy/host/README.md`. If container deployment fails, CTFd metadata is not
advanced to the broken revision.

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

Install `deploy/scoreboard/backup.env.example` as
`/etc/noco/backup.env`, owned by root with mode `600`; its database password
must match the scoreboard `.env`. The script loads this file itself, including
when cron supplies no environment.

```sh
# hourly during the event, daily otherwise (cron on the scoreboard host):
0 * * * * /opt/noco/deploy/scoreboard/backup.sh >> /var/log/noco-backup.log 2>&1
```

`backup.sh` dumps MariaDB and the explicitly named uploads volume, keeps the
last 48 locally, and pushes off-host if `NOCO_BACKUP_REMOTE` is set (an rclone
remote). **Set it.** A backup that lives only on the box you're restoring is
not a backup.
Practice `restore.sh` against a throwaway host once before the event — an
untested restore is a hope, not a plan.

Challenges need no backup: they're rebuilt from git and carry no player state.

## Event-day runbook

**One organizer owns the scoreboard** and is not writing or solving challenges
during the event. This does not rotate.

Common operations, all from the challenge host:

```sh
make -C deploy/chals ps                       # health of every challenge
make -C deploy/chals logs S=web-ghostdex   # tail one challenge
make -C deploy/chals restart S=pwn-municipal-connectivity-test    # bounce one challenge
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

- [ ] Two VMs provisioned; DigitalOcean Cloud Firewalls limit ingress to
      `80/443`, challenge `30000–30099`, and SSH from the organizer/VPN CIDR.
- [ ] Challenge web network is internal; `noco-container-firewall.service` is
      active and a test container on `noco-isolated` cannot initiate egress.
- [ ] DNS pointed; domain on an ACME-capable provider; wildcard cert issued
      (hit `https://up.chal.nocohackers.com`).
- [ ] GitHub `production` environment has the deploy variables/secrets from
      `deploy/host/README.md`; one `main` push has completed deploy and cleanup.
- [ ] CTFd up, themed, scoring decided, rate limits on, Redis sessions on.
- [ ] Backups running hourly **and pushing off-host**; a restore rehearsed.
- [ ] Full dry run: deploy everything from a clean clone, and have an organizer
      who didn't write them solve five challenges at random.
- [ ] Every challenge green in CI; `state: hidden` until kickoff.
- [ ] Scoreboard owner named.

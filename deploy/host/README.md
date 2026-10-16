# Production host automation

The production boundary remains **two VPSes**: one `scoreboard`, one `chals`.
These scripts bootstrap and deploy either role, so a newly-created VPS can be
brought online without maintaining a full repository checkout on it.

From an operator checkout:

```sh
# First connection uses the root key DigitalOcean installed.
make host-bootstrap ROLE=chals HOST=root@203.0.113.10

# The bootstrap copies that key to the unprivileged deploy account.
make host-sync ROLE=chals HOST=noco@203.0.113.10
```

Before `host-up`, install the role's secrets.

## Challenge host

```sh
# Remote: DNS-01 token and private GHCR authentication.
scp deploy/chals/dns.env.example noco@203.0.113.10:/opt/noco/deploy/chals/dns.env
ssh noco@203.0.113.10 'chmod 600 /opt/noco/deploy/chals/dns.env'
ssh noco@203.0.113.10 'docker login ghcr.io -u YOUR_GITHUB_USER'

make host-up ROLE=chals HOST=noco@203.0.113.10

# This must time out/fail; the daemon may pull alpine before attaching it.
ssh noco@203.0.113.10 \
  "docker run --rm --network noco-isolated alpine wget -T 3 -qO- https://example.com"
```

Use a GitHub token with read-only package access. The DigitalOcean token in
`dns.env` needs DNS write access for wildcard ACME renewal; it is not the token
used by `doctl` on the operator machine.

## Scoreboard host

```sh
make host-bootstrap ROLE=scoreboard HOST=root@203.0.113.20
make host-sync ROLE=scoreboard HOST=noco@203.0.113.20
scp deploy/scoreboard/.env.example noco@203.0.113.20:/opt/noco/deploy/scoreboard/.env
# Edit the remote file and replace every placeholder with generated secrets.
make host-up ROLE=scoreboard HOST=noco@203.0.113.20
```

Install `deploy/scoreboard/backup.env.example` as `/etc/noco/backup.env` (mode
`600`), configure rclone for `noco`, and only then add the documented cron job.

`deploy/host/deploy.sh` accepts `sync` to upload without starting services and
`up` to sync then converge the role. It deliberately excludes plaintext secret
files from rsync deletion.

## Historical automatic deployment from GitHub

During the event, the main CI workflow deployed the challenge host after
publishing images and before syncing CTFd. It ran for pushes to `main`; manual
runs on other branches could not publish or deploy. Because GitHub-hosted
runners have changing addresses, the job added its public `/32` to the
DigitalOcean Cloud Firewall for the duration of the SSH deployment and removed
it in an `always()` cleanup step. The workflow is not included in the public
archive.

Create a dedicated key; do not reuse an organizer's SSH identity:

```sh
HOST=203.0.113.10
install -d -m 700 ~/.config/noco
ssh-keygen -t ed25519 -N '' \
  -C noco-github-actions-chals \
  -f ~/.config/noco/github-actions-chals
{ printf 'restrict '; cat ~/.config/noco/github-actions-chals.pub; } |
  ssh noco@$HOST 'umask 077; cat >> ~/.ssh/authorized_keys'

# Build a pinned known_hosts line from the host key over the already-trusted
# organizer connection. Store the resulting line as the secret below.
ssh root@$HOST 'cat /etc/ssh/ssh_host_ed25519_key.pub' |
  awk -v host="$HOST" '{print host, $1, $2}'
```

The workflow used the following values in a protected GitHub **`production`
environment**:

| kind | name | value |
|------|------|-------|
| variable | `CHALLENGE_HOST` | challenge VPS IPv4 or hostname |
| variable | `CHALLENGE_FIREWALL_ID` | ID of the `noco-chals` Cloud Firewall |
| secret | `CHALLENGE_SSH_PRIVATE_KEY` | contents of the dedicated private key |
| secret | `CHALLENGE_SSH_KNOWN_HOSTS` | pinned known-hosts line produced above |
| secret | `DIGITALOCEAN_ACCESS_TOKEN` | token limited to firewall read/write |
| secret | `CTFCLI_ACCESS_TOKEN` | CTFd admin API token used by the following sync job |


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
# Local: commit the real sops-encrypted file first.
test -s deploy/chals/flags.enc.env

# Remote: DNS-01 token, age identity, and private GHCR authentication.
scp deploy/chals/dns.env.example noco@203.0.113.10:/opt/noco/deploy/chals/dns.env
scp keys.txt noco@203.0.113.10:~/.config/sops/age/keys.txt
ssh noco@203.0.113.10 'chmod 600 /opt/noco/deploy/chals/dns.env ~/.config/sops/age/keys.txt'
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

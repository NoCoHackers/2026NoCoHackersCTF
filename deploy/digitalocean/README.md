# DigitalOcean edge configuration

`configure.sh` manages the provider-side pieces for an **existing** Droplet:

- a role-specific Cloud Firewall;
- when the zone is visible in the current DigitalOcean account, the role's A
  records derived from `event.yml`.

Install and authenticate `doctl`, then run from the repository root:

```sh
export NOCO_SSH_CIDR=198.51.100.24/32   # organizer or VPN egress; never 0.0.0.0/0
make do-configure ROLE=chals DROPLET_ID=123456789 IPV4=203.0.113.10
make do-configure ROLE=scoreboard DROPLET_ID=987654321 IPV4=203.0.113.20
```

The script creates or replaces firewalls named `noco-chals` and
`noco-scoreboard`. Challenge ingress is SSH from `NOCO_SSH_CIDR`, HTTP/HTTPS,
and TCP `30000-30099`; scoreboard ingress is SSH plus HTTP/HTTPS. Outbound
traffic is allowed for host updates, image pulls, DNS, and ACME. Challenge
**container** egress is separately denied by the host bootstrap's Docker
network and `DOCKER-USER` policy.

The DNS changes intentionally leave apex and `www` records alone. The script
supports either the full base zone in DigitalOcean or separately delegated
`ctf.<base>` and `chal.<base>` zones. In the parent-zone layout it upserts
`ctf`, `chal`, `*.chal`, and `up.chal`; in delegated zones it writes the
corresponding `@`, `*`, and `up` records. If neither applicable zone is visible
to the token, it warns and configures only the Cloud Firewall.

To delegate while keeping the parent at another provider, create the two child
zones in DigitalOcean, then add `NS` records for `ctf` and `chal` at the parent
provider pointing to `ns1.digitalocean.com`, `ns2.digitalocean.com`, and
`ns3.digitalocean.com`. Do not replace the parent domain's nameservers.

The `doctl` credential remains on the operator machine. Do not copy a broad
DigitalOcean personal token to either VPS; Traefik receives only its DNS token
through the gitignored `deploy/chals/dns.env`.

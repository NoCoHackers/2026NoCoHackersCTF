#!/usr/bin/env bash
# Attach a least-ingress DigitalOcean Cloud Firewall and, when the event's DNS
# zone is in this account, upsert this role's records. `doctl auth init` must
# have been run with a token that can manage firewalls and droplets.
set -euo pipefail

ROLE=${1:-}
DROPLET_ID=${2:-}
IPV4=${3:-}
SSH_CIDR=${NOCO_SSH_CIDR:-}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

fatal() {
  echo "FATAL: $*" >&2
  exit 1
}

case "$ROLE" in
  chals|scoreboard) ;;
  *) fatal "usage: configure.sh <chals|scoreboard> <droplet-id> <public-ipv4>" ;;
esac
[[ $DROPLET_ID =~ ^[0-9]+$ ]] || fatal "droplet-id must be numeric (find it with: doctl compute droplet list)"
[[ $IPV4 =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fatal "a public IPv4 address is required"
[[ -n $SSH_CIDR ]] || fatal "set NOCO_SSH_CIDR to the organizer/VPN CIDR allowed to SSH (never default SSH to the world)"
command -v doctl >/dev/null || fatal "doctl is required: https://docs.digitalocean.com/reference/doctl/how-to/install/"
[[ -f $ROOT/deploy/domains.env ]] || fatal "deploy/domains.env is missing; run make domains"
# shellcheck disable=SC1091
. "$ROOT/deploy/domains.env"

dns_zone=
dns_names=()
if [[ ${NOCO_SKIP_DNS:-0} != 1 ]] && doctl compute domain get "$NOCO_APEX" >/dev/null 2>&1; then
  dns_zone=$NOCO_APEX
  if [[ $ROLE == scoreboard ]]; then
    dns_names=("${NOCO_SCOREBOARD_HOST%.$NOCO_APEX}")
  else
    challenge_label=${NOCO_CHALLENGE_BASE%.$NOCO_APEX}
    dns_names=("$challenge_label" "*.$challenge_label" "up.$challenge_label")
  fi
else
  # The parent can stay at a registrar while ctf.<base> and chal.<base> are
  # delegated to their own DigitalOcean zones.
  if [[ $ROLE == scoreboard ]]; then
    delegated_zone=$NOCO_SCOREBOARD_HOST
    delegated_names=("@")
  else
    delegated_zone=$NOCO_CHALLENGE_BASE
    delegated_names=("@" "*" "up")
  fi
  if [[ ${NOCO_SKIP_DNS:-0} != 1 ]] && doctl compute domain get "$delegated_zone" >/dev/null 2>&1; then
    dns_zone=$delegated_zone
    dns_names=("${delegated_names[@]}")
  else
    echo "WARNING: neither $NOCO_APEX nor $delegated_zone is visible in this doctl account; skipping DNS"
  fi
fi

firewall_name=${NOCO_FIREWALL_NAME:-noco-$ROLE}
inbound="protocol:tcp,ports:22,address:$SSH_CIDR"
inbound+=" protocol:tcp,ports:80,address:0.0.0.0/0 protocol:tcp,ports:80,address:::/0"
inbound+=" protocol:tcp,ports:443,address:0.0.0.0/0 protocol:tcp,ports:443,address:::/0"
if [[ $ROLE == chals ]]; then
  inbound+=" protocol:tcp,ports:30000-30099,address:0.0.0.0/0"
  inbound+=" protocol:tcp,ports:30000-30099,address:::/0"
fi
outbound="protocol:tcp,ports:all,address:0.0.0.0/0 protocol:tcp,ports:all,address:::/0"
outbound+=" protocol:udp,ports:all,address:0.0.0.0/0 protocol:udp,ports:all,address:::/0"
outbound+=" protocol:icmp,address:0.0.0.0/0 protocol:icmp,address:::/0"

firewall_id=$(doctl compute firewall list --format ID,Name --no-header | \
  awk -v name="$firewall_name" '$2 == name {print $1; exit}')
if [[ -n $firewall_id ]]; then
  echo "Updating cloud firewall $firewall_name ($firewall_id)"
  doctl compute firewall update "$firewall_id" \
    --name "$firewall_name" --droplet-ids "$DROPLET_ID" \
    --inbound-rules "$inbound" --outbound-rules "$outbound" >/dev/null
else
  echo "Creating cloud firewall $firewall_name"
  doctl compute firewall create \
    --name "$firewall_name" --droplet-ids "$DROPLET_ID" \
    --inbound-rules "$inbound" --outbound-rules "$outbound" >/dev/null
fi

if [[ -z $dns_zone ]]; then
  echo "DigitalOcean firewall is configured for $ROLE droplet $DROPLET_ID; DNS is unchanged."
  exit 0
fi

upsert_a() {
  local name=$1 id fqdn
  [[ $name == @ ]] && fqdn=$dns_zone || fqdn=$name.$dns_zone
  id=$(doctl compute domain records list "$dns_zone" \
    --format ID,Type,Name,Data --no-header | \
    awk -v name="$name" '$2 == "A" && $3 == name {print $1; exit}')
  if [[ -n $id ]]; then
    echo "Updating A $fqdn -> $IPV4"
    doctl compute domain records update "$dns_zone" \
      --record-id "$id" --record-name "$name" --record-data "$IPV4" >/dev/null
  else
    echo "Creating A $fqdn -> $IPV4"
    doctl compute domain records create "$dns_zone" \
      --record-type A --record-name "$name" --record-data "$IPV4" >/dev/null
  fi
}

for name in "${dns_names[@]}"; do
  upsert_a "$name"
done

echo "DigitalOcean firewall and DNS are configured for $ROLE droplet $DROPLET_ID."

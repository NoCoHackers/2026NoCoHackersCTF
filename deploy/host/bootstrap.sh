#!/usr/bin/env bash
# Prepare a fresh Debian/Ubuntu VPS for one NoCo production role.
# Run as root, usually through `make host-bootstrap` from an operator machine.
set -euo pipefail

ROLE=${1:-}
DEPLOY_USER=${NOCO_DEPLOY_USER:-noco}
INSTALL_ROOT=${NOCO_INSTALL_ROOT:-/opt/noco}
SOPS_VERSION=${SOPS_VERSION:-3.9.4}

fatal() {
  echo "FATAL: $*" >&2
  exit 1
}

case "$ROLE" in
  chals|scoreboard) ;;
  *) fatal "usage: bootstrap.sh <chals|scoreboard>" ;;
esac

[[ $EUID -eq 0 ]] || fatal "run this script as root"
[[ -r /etc/os-release ]] || fatal "cannot identify this operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) fatal "supported hosts are Ubuntu or Debian; found ${ID:-unknown}" ;;
esac

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg make rsync unattended-upgrades

if ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "$ID" "$VERSION_CODENAME" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
install -d -m 0750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$INSTALL_ROOT"

# A DigitalOcean root key is copied to the deploy account so the next SSH
# connection can stop using root. Never invent a password or weaken sshd.
if [[ -s /root/.ssh/authorized_keys && ! -s /home/$DEPLOY_USER/.ssh/authorized_keys ]]; then
  install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
  install -m 0600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    /root/.ssh/authorized_keys "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi

if [[ $ROLE == chals ]]; then
  apt-get install -y age iptables

  if ! command -v sops >/dev/null 2>&1; then
    arch=$(dpkg --print-architecture)
    case "$arch" in
      amd64|arm64) ;;
      *) fatal "no pinned sops package for architecture $arch" ;;
    esac
    tmp=$(mktemp --suffix=.deb)
    trap 'rm -f "$tmp"' EXIT
    curl -fsSL \
      "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops_${SOPS_VERSION}_${arch}.deb" \
      -o "$tmp"
    dpkg -i "$tmp"
    rm -f "$tmp"
    trap - EXIT
  fi

  install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    "/home/$DEPLOY_USER/.config/sops/age"

  # Web challenges use an internal bridge shared only with Traefik. TCP
  # challenges need a normal bridge for published ports, so DOCKER-USER drops
  # new outbound/lateral connections while retaining replies to players.
  docker network inspect noco-edge >/dev/null 2>&1 || \
    docker network create --internal --subnet 172.30.0.0/24 noco-edge >/dev/null
  docker network inspect noco-isolated >/dev/null 2>&1 || \
    docker network create --subnet 172.31.0.0/24 \
      --opt com.docker.network.bridge.enable_icc=false noco-isolated >/dev/null

  cat > /usr/local/sbin/noco-container-firewall <<'EOF'
#!/bin/sh
set -eu
CHAIN=DOCKER-USER
SUBNET=172.31.0.0/24
iptables -nL "$CHAIN" >/dev/null 2>&1 || {
  echo "FATAL: Docker has not created $CHAIN" >&2
  exit 1
}
iptables -C "$CHAIN" -s "$SUBNET" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN 2>/dev/null || \
  iptables -I "$CHAIN" 1 -s "$SUBNET" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -C "$CHAIN" -s "$SUBNET" -j DROP 2>/dev/null || \
  iptables -I "$CHAIN" 2 -s "$SUBNET" -j DROP
EOF
  chmod 0755 /usr/local/sbin/noco-container-firewall

  cat > /etc/systemd/system/noco-container-firewall.service <<'EOF'
[Unit]
Description=NoCo challenge-container egress policy
Requires=docker.service
After=docker.service
PartOf=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/noco-container-firewall
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now noco-container-firewall.service
else
  apt-get install -y rclone
  install -d -m 0750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /var/backups/noco
  install -d -m 0750 -o root -g "$DEPLOY_USER" /etc/noco
fi

cat <<EOF
Bootstrap complete for role: $ROLE
Deploy account: $DEPLOY_USER
Install root:   $INSTALL_ROOT

Next: reconnect as $DEPLOY_USER, then sync the role from your operator machine.
EOF
if [[ $ROLE == chals ]]; then
  cat <<EOF
Before the first start, install:
  /home/$DEPLOY_USER/.config/sops/age/keys.txt  (mode 600)
  $INSTALL_ROOT/deploy/chals/dns.env            (mode 600)
And authenticate Docker to private GHCR packages with a read-only token.
EOF
else
  cat <<EOF
Before the first start, install:
  $INSTALL_ROOT/deploy/scoreboard/.env          (mode 600)
  /etc/noco/backup.env                          (mode 600, root:$DEPLOY_USER)
And configure an off-host rclone destination.
EOF
fi

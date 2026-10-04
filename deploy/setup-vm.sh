#!/usr/bin/env bash
# One-time setup of InventoryTracker on a fresh Linux server. Supported:
#   Ubuntu 22.04/24.04, Debian 12, AlmaLinux / Rocky Linux / RHEL 8-9, CentOS Stream 9.
#
#   curl -fsSL https://raw.githubusercontent.com/DanTransfat/InventoryTracker/main/deploy/setup-vm.sh | sudo bash
#
# Run it as root, or as a user allowed to use sudo. Logged in as root, `| bash` is enough.
#
# Optional environment variables (put them after `sudo`, e.g. `sudo DOMAIN=inv.example.com bash`):
#   DOMAIN    your own hostname whose DNS A record points at this server.
#             Default: <public-ip>.sslip.io, a free hostname that resolves to your IP,
#             so you get real HTTPS with no domain to buy or configure.
#   REPO_URL  git repository to deploy (default: this project's GitHub repo)
#   APP_DIR   where to put it (default: /opt/inventory-tracker)
#
# Safe to run again: it skips anything already done and never overwrites .env.
set -euo pipefail

# Everything is inside main() so bash reads the whole script before running any of it.
# That matters for `curl ... | sudo bash`: otherwise a command that reads stdin could
# swallow the rest of the script.
main() {

REPO_URL="${REPO_URL:-https://github.com/DanTransfat/InventoryTracker.git}"
APP_DIR="${APP_DIR:-/opt/inventory-tracker}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "this needs root (it installs Docker and opens firewall ports).
Log in as root and run it again, or use an account that can run sudo."

# Which Linux family is this? /etc/os-release is standard on every supported distro.
# shellcheck disable=SC1090
. "${OS_RELEASE_FILE:-/etc/os-release}"
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*) family=debian ;;
  *" rhel "*|*" centos "*|*" fedora "*|*" almalinux "*|*" rocky "*) family=rhel ;;
  *) die "unsupported Linux (${PRETTY_NAME:-unknown}). Use Ubuntu, Debian, AlmaLinux, Rocky or RHEL." ;;
esac
echo "Detected ${PRETTY_NAME:-$ID} ($family family)."

say "1/6 Installing Docker, git and curl"
if [ "$family" = debian ]; then
  apt-get update -qq
  apt-get install -y -qq git curl ca-certificates openssl >/dev/null
  if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
  fi
else
  dnf install -y -q git curl ca-certificates openssl tar >/dev/null
  if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    # Docker's own packages. Podman (preinstalled on some images) conflicts with them.
    dnf remove -y -q podman buildah runc >/dev/null 2>&1 || true
    repo=centos; [ "${ID:-}" = rhel ] && repo=rhel; [ "${ID:-}" = fedora ] && repo=fedora
    curl -fsSL "https://download.docker.com/linux/$repo/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
fi
docker compose version >/dev/null || die "Docker Compose plugin is missing."
systemctl enable --now docker >/dev/null 2>&1 || true

say "2/6 Adding swap if this server has under 2 GB of memory"
# MySQL plus building the frontend can exceed 1 GB; swap prevents out-of-memory kills.
mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 2000000 ] && [ -z "$(swapon --show --noheadings)" ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "Added a 2 GB swap file."
else
  echo "Not needed."
fi

say "3/6 Opening ports 22 (SSH), 80 and 443 in the server firewall"
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
  ufw status | sed -n '1,12p'
elif systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd -q --permanent --add-service=ssh --add-service=http --add-service=https
  firewall-cmd -q --permanent --add-port=443/udp
  firewall-cmd -q --reload
  echo "firewalld: $(firewall-cmd --list-services)"
else
  echo "No server firewall running; relying on your cloud provider's firewall."
fi

say "4/6 Getting the code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

say "5/6 Writing .env with random passwords"
if [ -f .env ]; then
  echo ".env already exists; keeping it."
else
  public_ip=$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || true)
  if [ -z "${DOMAIN:-}" ]; then
    [ -n "$public_ip" ] || die "could not detect the public IP. Re-run with DOMAIN=<hostname>."
    DOMAIN="$(echo "$public_ip" | tr '.' '-').sslip.io"
  fi
  umask 077
  cat > .env <<EOF
# Generated by deploy/setup-vm.sh on $(date -u +%Y-%m-%dT%H:%MZ). Keep this file private.
SITE_ADDRESS=$DOMAIN
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)
MYSQL_DATABASE=inventory
MYSQL_USER=inventory
MYSQL_PASSWORD=$(openssl rand -hex 24)
LOG_LEVEL=INFO
ALERT_NOTIFIER=log
EOF
  echo "Site address: $DOMAIN"
fi
site=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2-)

say "6/6 Building and starting (first build takes 3-8 minutes)"
"${COMPOSE[@]}" up -d --build

echo "Waiting for the app to answer..."
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    "${COMPOSE[@]}" ps
    cat <<EOF

InventoryTracker is running.

  Open:    https://$site
  (The first visit can take up to a minute while the HTTPS certificate is issued.)

  Logs:    cd $APP_DIR && ${COMPOSE[*]} logs -f
  Update:  sudo $APP_DIR/deploy/update.sh
EOF
    exit 0
  fi
  sleep 5
done
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=50
die "the app did not become healthy within 5 minutes. The logs above usually say why."
}

main "$@"

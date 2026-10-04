#!/usr/bin/env bash
# One-time setup of InventoryTracker on a Linux server. Supported:
#   Ubuntu 22.04/24.04, Debian 12, AlmaLinux / Rocky Linux / RHEL 8-9, CentOS Stream 9.
#
#   curl -fsSL https://raw.githubusercontent.com/DanTransfat/InventoryTracker/main/deploy/setup-vm.sh | bash
#
# Two ways to make the app reachable (MODE):
#   https   (default) Caddy listens on ports 80/443 and gets a free HTTPS certificate.
#           Needs inbound ports 80 and 443 open.
#   tunnel  No inbound ports at all. A Cloudflare Tunnel connects OUT to Cloudflare, which
#           gives you a random https://<words>.trycloudflare.com address. Free and needs
#           no account; the address changes whenever the tunnel restarts.
#
# Who can run it:
#   - root, or a sudo user (`... | sudo bash`): can also install Docker, add swap and open ports.
#   - any user who can already run `docker` (member of the docker group), with no sudo:
#     those privileged steps are skipped and the app goes in ~/inventory-tracker.
#
# Optional environment variables (e.g. `... | MODE=tunnel bash`, or after sudo):
#   MODE      https | tunnel (see above). On a re-run, changing it switches modes.
#   DOMAIN    https mode: your own hostname whose DNS A record points at this server.
#             Default: <public-ip>.sslip.io, a free hostname that resolves to your IP.
#   REPO_URL  git repository to deploy (default: this project's GitHub repo)
#   APP_DIR   where to put it (default: /opt/inventory-tracker as root, else ~/inventory-tracker)
#
# Safe to run again: it skips anything already done and never overwrites passwords.
set -euo pipefail

# Everything is inside main() so bash reads the whole script before running any of it.
# That matters for `curl ... | bash`: otherwise a command that reads stdin could
# swallow the rest of the script.
main() {

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

REPO_URL="${REPO_URL:-https://github.com/DanTransfat/InventoryTracker.git}"
MODE_GIVEN="${MODE:-}"
MODE="${MODE:-https}"
case "$MODE" in https|tunnel) ;; *) die "MODE must be 'https' or 'tunnel' (got '$MODE')." ;; esac

if [ "$(id -u)" -eq 0 ]; then
  is_root=1
  APP_DIR="${APP_DIR:-/opt/inventory-tracker}"
else
  is_root=0
  APP_DIR="${APP_DIR:-$HOME/inventory-tracker}"
  docker info >/dev/null 2>&1 || die "this user can't use Docker, and isn't root.
Either log in as root (or a sudo user) and run it with sudo,
or add this user to the docker group as root: usermod -aG docker $(id -un)
then log out and back in."
fi

# Which Linux family is this? /etc/os-release is standard on every supported distro.
# shellcheck disable=SC1090
. "${OS_RELEASE_FILE:-/etc/os-release}"
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*) family=debian ;;
  *" rhel "*|*" centos "*|*" fedora "*|*" almalinux "*|*" rocky "*) family=rhel ;;
  *) family=other ;;
esac
echo "Detected ${PRETTY_NAME:-$ID}. Mode: $MODE. Running as $( [ $is_root = 1 ] && echo root || echo "$(id -un) (no root)" )."

say "1/6 Docker, git and curl"
if [ $is_root = 1 ]; then
  case "$family" in
    debian) apt-get update -qq && apt-get install -y -qq git curl ca-certificates openssl >/dev/null ;;
    rhel)   dnf install -y -q git curl ca-certificates openssl tar >/dev/null ;;
  esac
fi
for tool in git curl openssl; do
  command -v "$tool" >/dev/null || die "'$tool' is missing. Install it (as root), then run this again."
done
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  note "Docker is already installed: $(docker --version). Skipping the install."
elif [ $is_root = 0 ]; then
  die "Docker Compose v2 ('docker compose') is missing, and installing it needs root."
else
  case "$family" in
    debian) curl -fsSL https://get.docker.com | sh ;;
    rhel)
      # Docker's own packages. Podman (preinstalled on some images) conflicts with them.
      dnf remove -y -q podman buildah runc >/dev/null 2>&1 || true
      repo=centos; [ "${ID:-}" = rhel ] && repo=rhel; [ "${ID:-}" = fedora ] && repo=fedora
      curl -fsSL "https://download.docker.com/linux/$repo/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
      dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin ;;
    *) die "can't install Docker automatically on ${PRETTY_NAME:-this system}. Install Docker, then run this again." ;;
  esac
  docker compose version >/dev/null || die "Docker Compose plugin is missing after install."
fi
if [ $is_root = 1 ]; then systemctl enable --now docker >/dev/null 2>&1 || true; fi

say "2/6 Swap (only on servers with under 2 GB of memory)"
# MySQL plus building the frontend can exceed 1 GB; swap prevents out-of-memory kills.
mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if [ "$mem_kb" -ge 2000000 ] || [ -n "$(swapon --show --noheadings 2>/dev/null)" ]; then
  note "Not needed."
elif [ $is_root = 0 ]; then
  note "Under 2 GB of memory and no swap, but adding swap needs root. The first build may fail."
else
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  note "Added a 2 GB swap file."
fi

say "3/6 Firewall"
if [ "$MODE" = tunnel ]; then
  note "Tunnel mode needs no inbound ports. Nothing to open."
elif [ $is_root = 0 ]; then
  note "Skipped (needs root). Make sure inbound ports 80 and 443 are open."
elif command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
  note "ufw: allowed SSH, 80 and 443."
elif systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd -q --permanent --add-service=ssh --add-service=http --add-service=https
  firewall-cmd -q --permanent --add-port=443/udp
  firewall-cmd -q --reload
  note "firewalld: $(firewall-cmd --list-services)"
else
  note "No server firewall running; relying on your provider's firewall for ports 80/443."
fi

say "4/6 Code in $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

say "5/6 Settings (.env)"
https_site() {  # the hostname Caddy should get a certificate for
  if [ -n "${DOMAIN:-}" ]; then echo "$DOMAIN"; return; fi
  local ip
  ip=$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || true)
  [ -n "$ip" ] || die "could not detect the public IP. Re-run with DOMAIN=<hostname>."
  echo "$(echo "$ip" | tr '.' '-').sslip.io"
}
if [ "$MODE" = tunnel ]; then
  compose_file="docker-compose.yml:docker-compose.prod.yml:docker-compose.tunnel.yml"
else
  compose_file="docker-compose.yml:docker-compose.prod.yml"
fi
if [ -f .env ]; then
  note ".env already exists; keeping its passwords."
  # COMPOSE_FILE tells every later `docker compose` command which files to use.
  if ! grep -q '^COMPOSE_FILE=' .env; then
    echo "COMPOSE_FILE=$compose_file" >> .env
  elif [ -n "$MODE_GIVEN" ]; then
    sed -i "s#^COMPOSE_FILE=.*#COMPOSE_FILE=$compose_file#" .env
    note "Switched to $MODE mode."
  fi
  # https needs a real hostname; a .env first made in tunnel mode has the placeholder ":80".
  # An explicit DOMAIN also replaces whatever hostname was there.
  current=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2- || true)
  if [ "$MODE" = https ] && grep -q '^COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml$' .env \
     && { [ -z "$current" ] || [ "$current" = ":80" ] || [ -n "${DOMAIN:-}" ]; }; then
    site=$(https_site)
    if grep -q '^SITE_ADDRESS=' .env; then sed -i "s#^SITE_ADDRESS=.*#SITE_ADDRESS=$site#" .env
    else echo "SITE_ADDRESS=$site" >> .env; fi
    note "HTTPS address: $site"
  fi
else
  site=":80"   # tunnel mode: Caddy isn't used
  [ "$MODE" = https ] && site=$(https_site)
  (
    umask 077
    cat > .env <<EOF
# Generated by deploy/setup-vm.sh on $(date -u +%Y-%m-%dT%H:%MZ). Keep this file private.
COMPOSE_FILE=$compose_file
SITE_ADDRESS=$site
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)
MYSQL_DATABASE=inventory
MYSQL_USER=inventory
MYSQL_PASSWORD=$(openssl rand -hex 24)
LOG_LEVEL=INFO
ALERT_NOTIFIER=log
EOF
  )
  note "Wrote .env with random passwords (readable only by $(id -un))."
fi

say "6/6 Building and starting (the first build takes 3-8 minutes)"
if grep -q 'docker-compose.tunnel.yml' .env; then
  # Coming from https mode: Caddy is switched off in tunnel mode but may still be running
  # (and holding ports 80/443). Remove its container; certificates stay in their volume.
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=$(basename "$PWD")" \
                      --filter "label=com.docker.compose.service=caddy")
  [ -z "$ids" ] || docker rm -f $ids >/dev/null
fi
docker compose up -d --build --remove-orphans

note "Waiting for the app to answer..."
healthy=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then healthy=1; break; fi
  sleep 5
done
if [ $healthy = 0 ]; then
  docker compose ps
  docker compose logs --tail=50
  die "the app did not become healthy within 5 minutes. The logs above usually say why."
fi

if grep -q 'docker-compose.tunnel.yml' .env; then
  url=""
  for _ in $(seq 1 30); do
    url=$(docker compose logs tunnel 2>/dev/null | grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)
    [ -n "$url" ] && break
    sleep 2
  done
  [ -n "$url" ] || url="(not found yet; run: cd $APP_DIR && docker compose logs tunnel | grep trycloudflare)"
  where="$url
  (Can take up to a minute to start answering. The address changes when the tunnel restarts.)"
else
  where="https://$(grep '^SITE_ADDRESS=' .env | cut -d= -f2-)
  (The first visit can take up to a minute while the HTTPS certificate is issued.)"
fi
docker compose ps
cat <<EOF

InventoryTracker is running.

  Open:    $where

  Logs:    cd $APP_DIR && docker compose logs -f
  Update:  $APP_DIR/deploy/update.sh$( [ $is_root = 1 ] && echo "   (with sudo if not root)" )
EOF
}

main "$@"

#!/usr/bin/env bash
# Deploy the latest code from GitHub:  /opt/inventory-tracker/deploy/update.sh  (or ~/inventory-tracker/...)
# Run it as the same user that ran setup-vm.sh (with sudo if that was root).
# Database data, .env and HTTPS certificates are kept. New migrations apply on startup.
# Which compose files to use (https or tunnel mode) comes from COMPOSE_FILE in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
docker compose ps
if grep -q 'docker-compose.tunnel.yml' .env 2>/dev/null; then
  sleep 5
  echo "Tunnel address (changes after a restart):"
  docker compose logs tunnel | grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
fi

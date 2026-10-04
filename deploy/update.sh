#!/usr/bin/env bash
# Deploy the latest code from GitHub:  sudo /opt/inventory-tracker/deploy/update.sh
# Database data, .env and HTTPS certificates are kept. New migrations apply on startup.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker image prune -f >/dev/null
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

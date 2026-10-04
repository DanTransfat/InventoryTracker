#!/usr/bin/env bash
# Dump the database to backups/inventory-<timestamp>.sql.gz and keep the newest 14.
#   sudo /opt/inventory-tracker/deploy/backup.sh
# Daily at 03:15 (run `sudo crontab -e` and add):
#   15 3 * * * /opt/inventory-tracker/deploy/backup.sh >/dev/null 2>&1
# Restore:
#   gunzip -c backups/<file>.sql.gz | docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" inventory'
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
out="backups/inventory-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
# --single-transaction gives a consistent snapshot without locking writers.
# --triggers keeps the ledger's append-only triggers in the dump.
docker compose exec -T mysql sh -c \
  'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --triggers --routines "$MYSQL_DATABASE"' \
  | gzip > "$out"
ls -1t backups/inventory-*.sql.gz | tail -n +15 | xargs -r rm --
echo "Wrote $out"

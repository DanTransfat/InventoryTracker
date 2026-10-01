"""Apply pending SQL migrations.  Usage:  python -m scripts.migrate"""
from __future__ import annotations

import logging
import sys
import time

from app.config import get_settings
from app.db import Database, apply_migrations

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("migrate")


def connect_with_retry(db: Database, attempts: int = 30):
    """MySQL in Docker can take a few seconds to accept connections."""
    for attempt in range(1, attempts + 1):
        try:
            return db.connect()
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts:
                raise
            log.info("Database not ready (%s); retrying in 2s...", exc.__class__.__name__)
            time.sleep(2)


def main() -> int:
    db = Database(get_settings().database_url)
    conn = connect_with_retry(db)
    try:
        applied = apply_migrations(db, conn)
    finally:
        conn.close()
    log.info("Applied %d migration(s): %s", len(applied), ", ".join(applied) or "none (up to date)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

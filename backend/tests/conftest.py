"""Test fixtures.

By default every test gets a fresh SQLite database file (fast, no server).
Set TEST_DATABASE_URL=mysql://user:pass@host:3306/inventory_test to run the exact
same suite against MySQL 8 (CI does this). The MySQL database is wiped per test.
"""
from __future__ import annotations

import os
from typing import Any

import pytest

from app import create_app
from app.config import Settings
from app.db import Database, apply_migrations

MYSQL_URL = os.environ.get("TEST_DATABASE_URL", "")


class RecordingNotifier:
    def __init__(self):
        self.opened: list[dict[str, Any]] = []

    def alert_opened(self, alert: dict[str, Any]) -> None:
        self.opened.append(alert)


def _reset_mysql(db: Database) -> None:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in ("alerts", "stock_transactions", "items", "schema_migrations"):
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        cur.close()
        apply_migrations(db, conn)
    finally:
        conn.close()


@pytest.fixture
def database_url(tmp_path) -> str:
    if MYSQL_URL:
        _reset_mysql(Database(MYSQL_URL))
        return MYSQL_URL
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db = Database(url)
    conn = db.connect()
    apply_migrations(db, conn)
    conn.close()
    return url


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def app(database_url, notifier):
    application = create_app(Settings(database_url=database_url, log_level="WARNING"), notifier=notifier)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_item(client):
    counter = {"n": 0}

    def _make(**overrides) -> dict[str, Any]:
        counter["n"] += 1
        body = {"sku": f"TEST-{counter['n']:03d}", "name": f"Test item {counter['n']}",
                "unit": "each", "reorder_threshold": 10}
        body.update(overrides)
        res = client.post("/api/items", json=body)
        assert res.status_code == 201, res.json
        return res.json

    return _make


@pytest.fixture
def move(client):
    """Record a stock movement and return the response."""

    def _move(item_id: int, type_: str, qty: int, **extra):
        return client.post(f"/api/items/{item_id}/transactions",
                           json={"type": type_, "quantity_change": qty, "created_by": "tester", **extra.pop("body", {})},
                           headers=extra.pop("headers", {}))

    return _move

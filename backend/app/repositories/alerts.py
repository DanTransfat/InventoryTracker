"""Data access for low-stock alerts."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import Tx

ALERT_COLUMNS = (
    "a.id, a.item_id, a.status, a.triggered_stock, a.threshold_at_trigger, a.created_at,"
    " a.acknowledged_at, a.acknowledged_by, a.resolved_at, a.resolution_reason, a.resolved_stock,"
    " i.sku AS item_sku, i.name AS item_name, i.current_stock AS item_current_stock,"
    " i.reorder_threshold AS item_reorder_threshold, i.unit AS item_unit"
)
ACTIVE = ("open", "acknowledged")


def get(tx: Tx, alert_id: int) -> dict[str, Any] | None:
    return tx.fetch_one(
        f"SELECT {ALERT_COLUMNS} FROM alerts a JOIN items i ON i.id = a.item_id WHERE a.id = :id",
        {"id": alert_id},
    )


def get_active_for_item(tx: Tx, item_id: int) -> dict[str, Any] | None:
    """Callers hold the item's row lock, so this read cannot race with another writer."""
    return tx.fetch_one(
        f"SELECT {ALERT_COLUMNS} FROM alerts a JOIN items i ON i.id = a.item_id"
        " WHERE a.item_id = :item_id AND a.status IN ('open', 'acknowledged')",
        {"item_id": item_id},
    )


def insert_open(tx: Tx, *, item_id: int, triggered_stock: int, threshold: int, now: datetime) -> int:
    return tx.execute(
        "INSERT INTO alerts (item_id, status, triggered_stock, threshold_at_trigger, created_at)"
        " VALUES (:item_id, 'open', :stock, :threshold, :now)",
        {"item_id": item_id, "stock": triggered_stock, "threshold": threshold, "now": now},
    )


def resolve(tx: Tx, alert_id: int, *, reason: str, stock: int, now: datetime) -> None:
    tx.execute(
        "UPDATE alerts SET status = 'resolved', resolved_at = :now, resolution_reason = :reason,"
        " resolved_stock = :stock WHERE id = :id AND status IN ('open', 'acknowledged')",
        {"now": now, "reason": reason, "stock": stock, "id": alert_id},
    )


def acknowledge(tx: Tx, alert_id: int, *, by: str | None, now: datetime) -> int:
    return tx.execute(
        "UPDATE alerts SET status = 'acknowledged', acknowledged_at = :now, acknowledged_by = :by"
        " WHERE id = :id AND status = 'open'",
        {"now": now, "by": by, "id": alert_id},
    )


def list_page(tx: Tx, *, statuses: list[str], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    placeholders = ", ".join(f":s{i}" for i in range(len(statuses)))
    params: dict[str, Any] = {f"s{i}": s for i, s in enumerate(statuses)}
    where = f" WHERE a.status IN ({placeholders})"
    total = int(tx.fetch_value(f"SELECT COUNT(*) AS n FROM alerts a{where}", params) or 0)
    # Active alerts: oldest problem first is less useful than newest; resolved: most recent first.
    rows = tx.fetch_all(
        f"SELECT {ALERT_COLUMNS} FROM alerts a JOIN items i ON i.id = a.item_id{where}"
        " ORDER BY a.created_at DESC, a.id DESC LIMIT :limit OFFSET :offset",
        {**params, "limit": limit, "offset": offset},
    )
    return rows, total


def counts(tx: Tx) -> dict[str, int]:
    rows = tx.fetch_all(
        "SELECT status, COUNT(*) AS n FROM alerts WHERE status IN ('open', 'acknowledged') GROUP BY status"
    )
    result = {"open": 0, "acknowledged": 0}
    for row in rows:
        result[row["status"]] = int(row["n"])
    return result

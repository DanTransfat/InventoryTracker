"""Data access for the stock ledger (append-only: there is no update or delete here)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import Tx

TXN_COLUMNS = (
    "id, item_id, type, quantity_change, balance_after, note, created_by, "
    "idempotency_key, created_at"
)


def insert(tx: Tx, *, item_id: int, type_: str, quantity_change: int, balance_after: int,
           note: str | None, created_by: str, idempotency_key: str | None, now: datetime) -> int:
    return tx.execute(
        "INSERT INTO stock_transactions (item_id, type, quantity_change, balance_after, note,"
        " created_by, idempotency_key, created_at)"
        " VALUES (:item_id, :type, :qty, :balance, :note, :created_by, :key, :now)",
        {"item_id": item_id, "type": type_, "qty": quantity_change, "balance": balance_after,
         "note": note, "created_by": created_by, "key": idempotency_key, "now": now},
    )


def get(tx: Tx, txn_id: int) -> dict[str, Any] | None:
    return tx.fetch_one(f"SELECT {TXN_COLUMNS} FROM stock_transactions WHERE id = :id", {"id": txn_id})


def get_by_idempotency_key(tx: Tx, key: str) -> dict[str, Any] | None:
    return tx.fetch_one(
        f"SELECT {TXN_COLUMNS} FROM stock_transactions WHERE idempotency_key = :key", {"key": key}
    )


def list_for_item(tx: Tx, item_id: int, *, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    total = int(tx.fetch_value(
        "SELECT COUNT(*) AS n FROM stock_transactions WHERE item_id = :item_id", {"item_id": item_id}
    ) or 0)
    # Newest first. id is monotonic, so it is a stable tie-breaker for equal timestamps.
    rows = tx.fetch_all(
        f"SELECT {TXN_COLUMNS} FROM stock_transactions WHERE item_id = :item_id"
        " ORDER BY id DESC LIMIT :limit OFFSET :offset",
        {"item_id": item_id, "limit": limit, "offset": offset},
    )
    return rows, total


def ledger_sum(tx: Tx, item_id: int) -> int:
    return int(tx.fetch_value(
        "SELECT COALESCE(SUM(quantity_change), 0) AS s FROM stock_transactions WHERE item_id = :id",
        {"id": item_id},
    ) or 0)


def history_points(tx: Tx, item_id: int, limit: int) -> list[dict[str, Any]]:
    """Most recent ``limit`` balances, returned oldest-first for charting."""
    rows = tx.fetch_all(
        "SELECT id, created_at, balance_after, quantity_change, type FROM stock_transactions"
        " WHERE item_id = :item_id ORDER BY id DESC LIMIT :limit",
        {"item_id": item_id, "limit": limit},
    )
    return list(reversed(rows))


def ledger_mismatches(tx: Tx) -> list[dict[str, Any]]:
    """Items whose cached stock disagrees with their ledger. Should always be empty."""
    return tx.fetch_all(
        "SELECT i.id, i.sku, i.current_stock, COALESCE(SUM(t.quantity_change), 0) AS ledger_stock"
        " FROM items i LEFT JOIN stock_transactions t ON t.item_id = i.id"
        " GROUP BY i.id, i.sku, i.current_stock"
        " HAVING i.current_stock <> COALESCE(SUM(t.quantity_change), 0)"
    )

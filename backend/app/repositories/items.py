"""Data access for items. Pure SQL in, plain dicts out; no business rules here."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import Tx

ITEM_COLUMNS = (
    "id, sku, name, description, unit, reorder_threshold, current_stock, "
    "is_archived, archived_at, created_at, updated_at"
)

# Whitelist: user input never reaches ORDER BY directly.
SORT_COLUMNS = {"name": "name", "sku": "sku", "current_stock": "current_stock"}


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def insert(tx: Tx, *, sku: str, name: str, description: str, unit: str,
           reorder_threshold: int, now: datetime) -> int:
    return tx.execute(
        "INSERT INTO items (sku, name, description, unit, reorder_threshold, current_stock,"
        " is_archived, created_at, updated_at)"
        " VALUES (:sku, :name, :description, :unit, :threshold, 0, 0, :now, :now)",
        {"sku": sku, "name": name, "description": description, "unit": unit,
         "threshold": reorder_threshold, "now": now},
    )


def get(tx: Tx, item_id: int, *, for_update: bool = False) -> dict[str, Any] | None:
    """``for_update=True`` takes an exclusive row lock held until the transaction ends.
    Every write path that changes stock or alert state starts here, which serialises
    concurrent writers *per item*."""
    sql = f"SELECT {ITEM_COLUMNS} FROM items WHERE id = :id"
    if for_update:
        sql += " FOR UPDATE"
    return tx.fetch_one(sql, {"id": item_id})


def get_by_sku(tx: Tx, sku: str) -> dict[str, Any] | None:
    return tx.fetch_one(f"SELECT {ITEM_COLUMNS} FROM items WHERE sku = :sku", {"sku": sku})


def update_fields(tx: Tx, item_id: int, fields: dict[str, Any], now: datetime) -> None:
    allowed = {"name", "description", "unit", "reorder_threshold", "is_archived", "archived_at"}
    assignments = [f"{col} = :{col}" for col in fields if col in allowed]
    params = {k: v for k, v in fields.items() if k in allowed}
    assignments.append("updated_at = :updated_at")
    params.update({"updated_at": now, "id": item_id})
    tx.execute(f"UPDATE items SET {', '.join(assignments)} WHERE id = :id", params)


def set_current_stock(tx: Tx, item_id: int, stock: int, now: datetime) -> None:
    tx.execute(
        "UPDATE items SET current_stock = :stock, updated_at = :now WHERE id = :id",
        {"stock": stock, "now": now, "id": item_id},
    )


def list_page(tx: Tx, *, search: str | None, low_stock_only: bool, include_archived: bool,
              sort: str, descending: bool, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if not include_archived:
        where.append("is_archived = 0")
    if low_stock_only:
        where.append("is_low_stock = 1")
    if search:
        # SKU: prefix match (can use the index). Name: substring match.
        where.append("(sku LIKE :sku_prefix ESCAPE '!' OR name LIKE :name_contains ESCAPE '!')")
        escaped = _escape_like(search)
        params["sku_prefix"] = escaped.upper() + "%"
        params["name_contains"] = "%" + escaped + "%"
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total = int(tx.fetch_value(f"SELECT COUNT(*) AS n FROM items{where_sql}", params) or 0)

    column = SORT_COLUMNS[sort]
    direction = "DESC" if descending else "ASC"
    rows = tx.fetch_all(
        f"SELECT {ITEM_COLUMNS} FROM items{where_sql}"
        f" ORDER BY {column} {direction}, id {direction} LIMIT :limit OFFSET :offset",
        {**params, "limit": limit, "offset": offset},
    )
    return rows, total

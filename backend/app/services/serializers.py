"""Turn database rows into the JSON shapes the API returns."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def item(row: dict[str, Any], active_alert: dict[str, Any] | None = None, *, include_alert: bool = False) -> dict[str, Any]:
    stock, threshold = int(row["current_stock"]), int(row["reorder_threshold"])
    data = {
        "id": int(row["id"]),
        "sku": row["sku"],
        "name": row["name"],
        "description": row["description"],
        "unit": row["unit"],
        "reorder_threshold": threshold,
        "current_stock": stock,
        # Single definition of "low": strictly below the threshold (README, open question 3).
        "is_low_stock": stock < threshold,
        "is_archived": bool(row["is_archived"]),
        "archived_at": iso(row["archived_at"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
    }
    if include_alert:
        data["active_alert"] = alert(active_alert) if active_alert else None
    return data


def transaction(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "item_id": int(row["item_id"]),
        "type": row["type"],
        "quantity_change": int(row["quantity_change"]),
        "balance_after": int(row["balance_after"]),
        "note": row["note"],
        "created_by": row["created_by"],
        "created_at": iso(row["created_at"]),
    }


def alert(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "item_id": int(row["item_id"]),
        "status": row["status"],
        "triggered_stock": int(row["triggered_stock"]),
        "threshold_at_trigger": int(row["threshold_at_trigger"]),
        "created_at": iso(row["created_at"]),
        "acknowledged_at": iso(row["acknowledged_at"]),
        "acknowledged_by": row["acknowledged_by"],
        "resolved_at": iso(row["resolved_at"]),
        "resolution_reason": row["resolution_reason"],
        "resolved_stock": row["resolved_stock"],
        "item": {
            "sku": row["item_sku"],
            "name": row["item_name"],
            "unit": row["item_unit"],
            "current_stock": int(row["item_current_stock"]),
            "reorder_threshold": int(row["item_reorder_threshold"]),
        },
    }


def page(items: list[dict[str, Any]], *, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "data": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, -(-total // page_size)),
    }

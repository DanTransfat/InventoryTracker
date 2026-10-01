"""HTTP layer: parse the request, call the service, shape the response. No SQL here."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from ..errors import BadRequest, ValidationFailed
from ..schemas import AlertAcknowledge, ItemCreate, ItemUpdate, TransactionCreate, parse_body
from ..services.inventory import InventoryService

bp = Blueprint("api", __name__, url_prefix="/api")

MAX_PAGE_SIZE = 100
ALERT_STATUSES = {"open", "acknowledged", "resolved"}


def service() -> InventoryService:
    if "service" not in g:
        db = current_app.extensions["db"]
        g.conn = db.connect()
        g.service = InventoryService(db, g.conn, current_app.extensions["notifier"])
    return g.service


def json_body() -> Any:
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise BadRequest("Request body is not valid JSON.", code="INVALID_JSON")
    return data


def int_arg(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValidationFailed(f"'{name}' must be a whole number.", fields={name: "Must be a whole number."}) from None
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum else f"at least {minimum}"
        raise ValidationFailed(f"'{name}' must be {bound}.", fields={name: f"Must be {bound}."})
    return value


def bool_arg(name: str) -> bool:
    return request.args.get(name, "").lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- items
@bp.get("/items")
def list_items():
    sort_raw = request.args.get("sort", "name")
    descending = sort_raw.startswith("-")
    sort = sort_raw.lstrip("-")
    if sort not in ("name", "sku", "current_stock"):
        raise ValidationFailed("Unsupported sort field.",
                               fields={"sort": "Use name, sku or current_stock (prefix '-' for descending)."})
    search = (request.args.get("search") or "").strip() or None
    if search and len(search) > 100:
        raise ValidationFailed("Search text is too long.", fields={"search": "At most 100 characters."})
    result = service().list_items(
        search=search,
        low_stock_only=bool_arg("low_stock"),
        include_archived=bool_arg("include_archived"),
        sort=sort,
        descending=descending,
        page=int_arg("page", 1),
        page_size=int_arg("page_size", 25, maximum=MAX_PAGE_SIZE),
    )
    return jsonify(result)


@bp.post("/items")
def create_item():
    data = parse_body(ItemCreate, json_body())
    item = service().create_item(data)
    return jsonify(item), 201, {"Location": f"/api/items/{item['id']}"}


@bp.get("/items/<int:item_id>")
def get_item(item_id: int):
    return jsonify(service().get_item(item_id))


@bp.patch("/items/<int:item_id>")
def update_item(item_id: int):
    data = parse_body(ItemUpdate, json_body())
    return jsonify(service().update_item(item_id, data))


@bp.get("/items/<int:item_id>/transactions")
def list_transactions(item_id: int):
    return jsonify(service().list_transactions(
        item_id, page=int_arg("page", 1), page_size=int_arg("page_size", 20, maximum=MAX_PAGE_SIZE)))


@bp.post("/items/<int:item_id>/transactions")
def record_transaction(item_id: int):
    data = parse_body(TransactionCreate, json_body())
    key = (request.headers.get("Idempotency-Key") or "").strip() or None
    if key and len(key) > 100:
        raise ValidationFailed("Idempotency-Key is too long (max 100 characters).",
                               fields={"Idempotency-Key": "At most 100 characters."})
    result = service().record_transaction(item_id, data, idempotency_key=key)
    body = {"transaction": result.transaction, "item": result.item, "alert_change": result.alert_change}
    headers = {"Idempotent-Replayed": "true"} if result.replayed else {}
    # A replay returns the original result with 200 instead of creating a second row.
    return jsonify(body), (200 if result.replayed else 201), headers


@bp.get("/items/<int:item_id>/stock-history")
def stock_history(item_id: int):
    return jsonify(service().stock_history(item_id, limit=int_arg("limit", 500, maximum=2000)))


# ---------------------------------------------------------------- alerts
@bp.get("/alerts")
def list_alerts():
    raw = request.args.get("status", "open,acknowledged")
    statuses = sorted({s.strip() for s in raw.split(",") if s.strip()})
    if not statuses or not set(statuses) <= ALERT_STATUSES:
        raise ValidationFailed("Unsupported alert status.",
                               fields={"status": "Use any of open, acknowledged, resolved (comma-separated)."})
    return jsonify(service().list_alerts(
        statuses=statuses, page=int_arg("page", 1), page_size=int_arg("page_size", 25, maximum=MAX_PAGE_SIZE)))


@bp.get("/alerts/summary")
def alert_summary():
    return jsonify(service().alert_counts())


@bp.post("/alerts/<int:alert_id>/acknowledge")
def acknowledge_alert(alert_id: int):
    data = parse_body(AlertAcknowledge, json_body())
    return jsonify(service().acknowledge_alert(alert_id, data.acknowledged_by or None))


# ---------------------------------------------------------------- ops
@bp.get("/health")
def health():
    service().alert_counts()  # touches the database
    return jsonify({"status": "ok"})


@bp.get("/integrity/ledger")
def ledger_check():
    """Proves the cached stock column agrees with the ledger. ``mismatches`` should be []."""
    mismatches = service().ledger_mismatches()
    return jsonify({"ok": not mismatches, "mismatches": mismatches})

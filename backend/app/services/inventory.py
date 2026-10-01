"""Business rules. Every write follows the same recipe:

    1. open ONE database transaction
    2. lock the item row (SELECT ... FOR UPDATE)
    3. validate against the locked, up-to-date state
    4. write the ledger row, the cached stock and the alert state
    5. commit (or roll back everything on any error)

Because step 2 serialises writers per item, two concurrent shipments cannot both see
"enough stock", and two concurrent drops cannot both decide to open an alert.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..db import Database, DuplicateKeyError, Tx
from ..errors import Conflict, NotFound, ValidationFailed
from ..repositories import alerts as alert_repo
from ..repositories import items as item_repo
from ..repositories import transactions as txn_repo
from ..schemas import ItemCreate, ItemUpdate, TransactionCreate
from . import serializers as ser
from .notifier import AlertNotifier, LogNotifier

POSITIVE_TYPES = {"received", "returned"}
NEGATIVE_TYPES = {"shipped"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AlertChange:
    action: str  # "opened" | "resolved"
    alert_id: int


@dataclass
class TransactionResult:
    transaction: dict[str, Any]
    item: dict[str, Any]
    alert_change: dict[str, Any] | None
    replayed: bool = False


class InventoryService:
    def __init__(self, db: Database, conn: Any, notifier: AlertNotifier | None = None,
                 clock: Callable[[], datetime] = utcnow):
        self.db = db
        self.conn = conn
        self.notifier = notifier or LogNotifier()
        self.clock = clock

    # ------------------------------------------------------------------ helpers
    def _write(self, fn: Callable[[Tx], Any]) -> Any:
        return self.db.run_in_transaction(self.conn, fn)

    def _read(self, fn: Callable[[Tx], Any]) -> Any:
        with self.db.transaction(self.conn, readonly=True) as tx:
            return fn(tx)

    def _notify_opened(self, change: AlertChange | None) -> None:
        """Called only after COMMIT, so we never announce an alert that was rolled back."""
        if change and change.action == "opened":
            row = self._read(lambda tx: alert_repo.get(tx, change.alert_id))
            if row:
                self.notifier.alert_opened(ser.alert(row))

    @staticmethod
    def _locked_item(tx: Tx, item_id: int) -> dict[str, Any]:
        item = item_repo.get(tx, item_id, for_update=True)
        if item is None:
            raise NotFound(f"Item {item_id} was not found.", code="ITEM_NOT_FOUND")
        return item

    def _evaluate_alert(self, tx: Tx, item: dict[str, Any], reason_if_resolved: str) -> AlertChange | None:
        """Apply the alert lifecycle to the item's current state. Caller holds the item lock.

        - low (stock < threshold) and no active alert  -> open one
        - low and an active alert exists               -> nothing (no duplicates)
        - not low (or archived) and an active alert    -> resolve it
        """
        now = self.clock()
        stock, threshold = int(item["current_stock"]), int(item["reorder_threshold"])
        is_low = not item["is_archived"] and stock < threshold
        active = alert_repo.get_active_for_item(tx, int(item["id"]))
        if is_low and active is None:
            alert_id = alert_repo.insert_open(tx, item_id=int(item["id"]), triggered_stock=stock,
                                              threshold=threshold, now=now)
            return AlertChange("opened", alert_id)
        if not is_low and active is not None:
            reason = "item_archived" if item["is_archived"] else reason_if_resolved
            alert_repo.resolve(tx, int(active["id"]), reason=reason, stock=stock, now=now)
            return AlertChange("resolved", int(active["id"]))
        return None

    def _append_movement(self, tx: Tx, item: dict[str, Any], *, type_: str, quantity_change: int,
                         note: str | None, created_by: str, idempotency_key: str | None
                         ) -> tuple[dict[str, Any], dict[str, Any], AlertChange | None]:
        """Write one ledger row and keep the cached stock + alert state in step with it."""
        now = self.clock()
        current = int(item["current_stock"])
        new_balance = current + quantity_change
        if new_balance < 0:
            raise Conflict(
                f"Insufficient stock: {current} {item['unit']} on hand, "
                f"cannot remove {-quantity_change}.",
                code="INSUFFICIENT_STOCK",
                fields={"quantity_change": f"Only {current} on hand."},
                details={"current_stock": current, "requested_change": quantity_change},
            )
        txn_id = txn_repo.insert(tx, item_id=int(item["id"]), type_=type_, quantity_change=quantity_change,
                                 balance_after=new_balance, note=note, created_by=created_by,
                                 idempotency_key=idempotency_key, now=now)
        item_repo.set_current_stock(tx, int(item["id"]), new_balance, now)
        updated = item_repo.get(tx, int(item["id"]))
        assert updated is not None
        change = self._evaluate_alert(tx, updated, reason_if_resolved="stock_recovered")
        txn = txn_repo.get(tx, txn_id)
        assert txn is not None
        return txn, updated, change

    # ------------------------------------------------------------------ items
    def create_item(self, data: ItemCreate) -> dict[str, Any]:
        def work(tx: Tx):
            if item_repo.get_by_sku(tx, data.sku) is not None:
                raise _duplicate_sku(data.sku)
            item_id = item_repo.insert(tx, sku=data.sku, name=data.name, description=data.description,
                                       unit=data.unit, reorder_threshold=data.reorder_threshold,
                                       now=self.clock())
            item = self._locked_item(tx, item_id)
            if data.initial_stock > 0:
                _, item, change = self._append_movement(
                    tx, item, type_="received", quantity_change=data.initial_stock,
                    note="Opening balance", created_by=data.created_by, idempotency_key=None)
            else:
                change = self._evaluate_alert(tx, item, reason_if_resolved="stock_recovered")
            return item_id, change

        try:
            item_id, change = self._write(work)
        except DuplicateKeyError as exc:
            # Two requests raced past the pre-check; the UNIQUE index is the real guard.
            if exc.constraint == "uq_items_sku":
                raise _duplicate_sku(data.sku) from None
            raise
        self._notify_opened(change)
        return self.get_item(item_id)

    def get_item(self, item_id: int) -> dict[str, Any]:
        def work(tx: Tx):
            item = item_repo.get(tx, item_id)
            if item is None:
                raise NotFound(f"Item {item_id} was not found.", code="ITEM_NOT_FOUND")
            return ser.item(item, alert_repo.get_active_for_item(tx, item_id), include_alert=True)

        return self._read(work)

    def update_item(self, item_id: int, data: ItemUpdate) -> dict[str, Any]:
        fields = data.model_dump(exclude_unset=True)
        nulls = {k: "Cannot be null." for k, v in fields.items() if v is None}
        if nulls:
            raise ValidationFailed("Some fields are invalid.", fields=nulls)

        def work(tx: Tx):
            item = self._locked_item(tx, item_id)
            updates = dict(fields)
            if "is_archived" in updates:
                if updates["is_archived"] and not item["is_archived"]:
                    updates["archived_at"] = self.clock()
                elif not updates["is_archived"]:
                    updates["archived_at"] = None
                updates["is_archived"] = 1 if updates["is_archived"] else 0
            if updates:
                item_repo.update_fields(tx, item_id, updates, self.clock())
            refreshed = item_repo.get(tx, item_id)
            # A threshold change or (un)archive re-evaluates the alert immediately.
            return self._evaluate_alert(tx, refreshed, reason_if_resolved="threshold_changed")

        change = self._write(work)
        self._notify_opened(change)
        return self.get_item(item_id)

    def list_items(self, *, search: str | None, low_stock_only: bool, include_archived: bool,
                   sort: str, descending: bool, page: int, page_size: int) -> dict[str, Any]:
        def work(tx: Tx):
            rows, total = item_repo.list_page(
                tx, search=search, low_stock_only=low_stock_only, include_archived=include_archived,
                sort=sort, descending=descending, limit=page_size, offset=(page - 1) * page_size)
            return ser.page([ser.item(r) for r in rows], page=page, page_size=page_size, total=total)

        return self._read(work)

    # ------------------------------------------------------------------ transactions
    def record_transaction(self, item_id: int, data: TransactionCreate,
                           idempotency_key: str | None = None) -> TransactionResult:
        _check_sign(data.type, data.quantity_change)

        def work(tx: Tx):
            item = self._locked_item(tx, item_id)
            if idempotency_key:
                # Checked *after* taking the lock: a concurrent retry with the same key
                # waits for us, then finds our row here.
                existing = txn_repo.get_by_idempotency_key(tx, idempotency_key)
                if existing is not None:
                    if not _same_request(existing, item_id, data):
                        raise _key_reused()
                    return existing, item, None, True
            if item["is_archived"]:
                raise Conflict("This item is archived. Restore it before recording stock movements.",
                               code="ITEM_ARCHIVED")
            txn, updated, change = self._append_movement(
                tx, item, type_=data.type, quantity_change=data.quantity_change, note=data.note or None,
                created_by=data.created_by, idempotency_key=idempotency_key)
            return txn, updated, change, False

        try:
            txn, item, change, replayed = self._write(work)
        except DuplicateKeyError as exc:
            if exc.constraint == "uq_txn_idempotency_key":
                raise _key_reused() from None
            raise
        self._notify_opened(change)
        return TransactionResult(
            transaction=ser.transaction(txn),
            item=self.get_item(item_id),
            alert_change={"action": change.action, "alert_id": change.alert_id} if change else None,
            replayed=replayed,
        )

    def list_transactions(self, item_id: int, *, page: int, page_size: int) -> dict[str, Any]:
        def work(tx: Tx):
            if item_repo.get(tx, item_id) is None:
                raise NotFound(f"Item {item_id} was not found.", code="ITEM_NOT_FOUND")
            rows, total = txn_repo.list_for_item(tx, item_id, limit=page_size, offset=(page - 1) * page_size)
            return ser.page([ser.transaction(r) for r in rows], page=page, page_size=page_size, total=total)

        return self._read(work)

    def stock_history(self, item_id: int, limit: int = 500) -> dict[str, Any]:
        def work(tx: Tx):
            if item_repo.get(tx, item_id) is None:
                raise NotFound(f"Item {item_id} was not found.", code="ITEM_NOT_FOUND")
            points = txn_repo.history_points(tx, item_id, limit)
            return {"data": [{"at": ser.iso(p["created_at"]), "stock": int(p["balance_after"]),
                              "change": int(p["quantity_change"]), "type": p["type"]} for p in points]}

        return self._read(work)

    # ------------------------------------------------------------------ alerts
    def list_alerts(self, *, statuses: list[str], page: int, page_size: int) -> dict[str, Any]:
        def work(tx: Tx):
            rows, total = alert_repo.list_page(tx, statuses=statuses, limit=page_size,
                                               offset=(page - 1) * page_size)
            return ser.page([ser.alert(r) for r in rows], page=page, page_size=page_size, total=total)

        return self._read(work)

    def alert_counts(self) -> dict[str, int]:
        return self._read(alert_repo.counts)

    def acknowledge_alert(self, alert_id: int, acknowledged_by: str | None) -> dict[str, Any]:
        def work(tx: Tx):
            alert = alert_repo.get(tx, alert_id)
            if alert is None:
                raise NotFound(f"Alert {alert_id} was not found.", code="ALERT_NOT_FOUND")
            if alert["status"] == "open":
                # Conditional UPDATE: atomic even if the alert resolves at the same moment.
                alert_repo.acknowledge(tx, alert_id, by=acknowledged_by, now=self.clock())
                alert = alert_repo.get(tx, alert_id)
            if alert["status"] == "resolved":
                raise Conflict("This alert is already resolved.", code="ALERT_RESOLVED")
            return ser.alert(alert)  # acknowledging twice is a harmless no-op

        return self._write(work)

    # ------------------------------------------------------------------ integrity
    def ledger_mismatches(self) -> list[dict[str, Any]]:
        return self._read(txn_repo.ledger_mismatches)


def _check_sign(type_: str, qty: int) -> None:
    if qty == 0:
        raise ValidationFailed("Quantity must be a non-zero whole number.",
                               fields={"quantity_change": "Must not be zero."})
    if type_ in POSITIVE_TYPES and qty < 0:
        raise ValidationFailed(f"A '{type_}' transaction must add stock (positive quantity).",
                               fields={"quantity_change": "Must be positive for this type."})
    if type_ in NEGATIVE_TYPES and qty > 0:
        raise ValidationFailed("A 'shipped' transaction must remove stock (negative quantity).",
                               fields={"quantity_change": "Must be negative for a shipment."})


def _same_request(existing: dict[str, Any], item_id: int, data: TransactionCreate) -> bool:
    return (int(existing["item_id"]) == item_id and existing["type"] == data.type
            and int(existing["quantity_change"]) == data.quantity_change
            and (existing["note"] or None) == (data.note or None)
            and existing["created_by"] == data.created_by)


def _duplicate_sku(sku: str) -> Conflict:
    return Conflict(f"An item with SKU '{sku}' already exists.", code="DUPLICATE_SKU",
                    fields={"sku": "This SKU is already in use."})


def _key_reused() -> Conflict:
    return Conflict("This Idempotency-Key was already used for a different request.",
                    code="IDEMPOTENCY_KEY_REUSED")

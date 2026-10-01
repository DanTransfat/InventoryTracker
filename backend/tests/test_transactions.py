"""FR-2 (record stock movements) and the ledger invariants."""
import pytest

from app.db import Database


@pytest.mark.parametrize("type_,qty", [("received", 5), ("returned", 2), ("adjustment", 3), ("adjustment", -1)])
def test_valid_movements_are_recorded(client, make_item, move, type_, qty):
    item = make_item(reorder_threshold=0, initial_stock=10)
    res = move(item["id"], type_, qty, body={"note": "hello"})
    assert res.status_code == 201
    assert res.json["transaction"]["quantity_change"] == qty
    assert res.json["transaction"]["balance_after"] == 10 + qty
    assert res.json["transaction"]["note"] == "hello"
    assert res.json["item"]["current_stock"] == 10 + qty


@pytest.mark.parametrize("type_,qty", [("received", -5), ("returned", -1), ("shipped", 3), ("adjustment", 0), ("shipped", 0)])
def test_sign_rules_are_enforced(make_item, move, type_, qty):
    item = make_item(initial_stock=10)
    res = move(item["id"], type_, qty)
    assert res.status_code == 422
    assert "quantity_change" in res.json["error"]["fields"]


@pytest.mark.parametrize("qty", [1.5, "3", None])
def test_quantity_must_be_whole_number(make_item, move, qty):
    item = make_item(initial_stock=10)
    assert move(item["id"], "received", qty).status_code == 422


def test_created_by_and_type_are_required(client, make_item):
    item = make_item()
    res = client.post(f"/api/items/{item['id']}/transactions", json={"type": "teleported", "quantity_change": 1})
    assert res.status_code == 422
    assert {"type", "created_by"} <= set(res.json["error"]["fields"])


def test_shipment_that_would_go_negative_is_409_and_nothing_is_saved(client, make_item, move):
    item = make_item(reorder_threshold=0, initial_stock=4)
    res = move(item["id"], "shipped", -5)
    assert res.status_code == 409
    assert res.json["error"]["code"] == "INSUFFICIENT_STOCK"
    assert res.json["error"]["details"] == {"current_stock": 4, "requested_change": -5}
    assert client.get(f"/api/items/{item['id']}").json["current_stock"] == 4
    assert client.get(f"/api/items/{item['id']}/transactions").json["total"] == 1


def test_adjustment_cannot_go_negative_either(make_item, move):
    item = make_item(initial_stock=2)
    assert move(item["id"], "adjustment", -3).status_code == 409
    assert move(item["id"], "adjustment", -2).status_code == 201  # exactly zero is fine


def test_movement_on_missing_or_archived_item(client, make_item, move):
    assert move(424242, "received", 1).status_code == 404
    item = make_item()
    client.patch(f"/api/items/{item['id']}", json={"is_archived": True})
    res = move(item["id"], "received", 1)
    assert res.status_code == 409 and res.json["error"]["code"] == "ITEM_ARCHIVED"


def test_history_is_newest_first_and_paginated(client, make_item, move):
    item = make_item(reorder_threshold=0)
    for qty in (1, 2, 3, 4, 5):
        move(item["id"], "received", qty)
    page1 = client.get(f"/api/items/{item['id']}/transactions?page_size=2").json
    assert page1["total"] == 5 and page1["total_pages"] == 3
    assert [t["quantity_change"] for t in page1["data"]] == [5, 4]
    page3 = client.get(f"/api/items/{item['id']}/transactions?page_size=2&page=3").json
    assert [t["quantity_change"] for t in page3["data"]] == [1]
    assert client.get("/api/items/999/transactions").status_code == 404


def test_transactions_cannot_be_edited_or_deleted_via_api(client, make_item, move):
    item = make_item(initial_stock=1)
    txn = client.get(f"/api/items/{item['id']}/transactions").json["data"][0]
    assert client.patch(f"/api/items/{item['id']}/transactions", json={}).status_code == 405
    assert client.delete(f"/api/items/{item['id']}/transactions").status_code == 405
    assert client.patch(f"/api/transactions/{txn['id']}", json={}).status_code == 404


def test_ledger_is_append_only_in_the_database(database_url, make_item):
    """Even code that bypasses the API cannot rewrite history."""
    make_item(initial_stock=3)
    db = Database(database_url)
    conn = db.connect()
    try:
        for sql in ("UPDATE stock_transactions SET quantity_change = 99", "DELETE FROM stock_transactions"):
            with pytest.raises(Exception, match="append-only"):
                with db.transaction(conn) as tx:
                    tx.execute(sql)
    finally:
        conn.close()


def test_cached_stock_always_matches_ledger(client, make_item, move):
    item = make_item(reorder_threshold=3, initial_stock=10)
    for type_, qty in [("shipped", -4), ("received", 7), ("adjustment", -2), ("shipped", -20),
                       ("returned", 1), ("shipped", -12)]:
        move(item["id"], type_, qty)
    stock = client.get(f"/api/items/{item['id']}").json["current_stock"]
    ledger = client.get(f"/api/items/{item['id']}/transactions?page_size=100").json["data"]
    assert stock == sum(t["quantity_change"] for t in ledger) == ledger[0]["balance_after"]
    assert client.get("/api/integrity/ledger").json == {"ok": True, "mismatches": []}


def test_stock_history_points_are_oldest_first(client, make_item, move):
    item = make_item(reorder_threshold=0, initial_stock=5)
    move(item["id"], "shipped", -2)
    move(item["id"], "received", 10)
    points = client.get(f"/api/items/{item['id']}/stock-history").json["data"]
    assert [p["stock"] for p in points] == [5, 3, 13]


def test_idempotency_key_replays_instead_of_duplicating(client, make_item, move):
    item = make_item(reorder_threshold=0, initial_stock=10)
    first = move(item["id"], "shipped", -3, headers={"Idempotency-Key": "abc-123"})
    again = move(item["id"], "shipped", -3, headers={"Idempotency-Key": "abc-123"})
    assert first.status_code == 201
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json["transaction"]["id"] == first.json["transaction"]["id"]
    assert client.get(f"/api/items/{item['id']}").json["current_stock"] == 7


def test_idempotency_key_reused_with_different_payload_is_409(make_item, move):
    item = make_item(reorder_threshold=0, initial_stock=10)
    other = make_item(reorder_threshold=0, initial_stock=10)
    move(item["id"], "shipped", -3, headers={"Idempotency-Key": "k1"})
    res = move(item["id"], "shipped", -4, headers={"Idempotency-Key": "k1"})
    assert res.status_code == 409 and res.json["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert move(other["id"], "shipped", -3, headers={"Idempotency-Key": "k1"}).status_code == 409

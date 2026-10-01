"""Non-functional requirement: data integrity under concurrency.

These tests fire real parallel requests (one DB connection per thread). On MySQL
they exercise SELECT ... FOR UPDATE row locks; on SQLite, the database write lock.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor


def run_parallel(n: int, fn):
    barrier = threading.Barrier(n)

    def task(i):
        barrier.wait()  # release all threads at the same instant
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(task, range(n)))


def test_parallel_shipments_never_oversell(app, client, make_item):
    item = make_item(reorder_threshold=5, initial_stock=10)

    def ship(_):
        res = app.test_client().post(f"/api/items/{item['id']}/transactions",
                                     json={"type": "shipped", "quantity_change": -1, "created_by": "bot"})
        return res.status_code

    codes = run_parallel(20, ship)
    assert codes.count(201) == 10
    assert codes.count(409) == 10
    assert client.get(f"/api/items/{item['id']}").json["current_stock"] == 0
    assert client.get("/api/integrity/ledger").json["ok"] is True
    active = client.get("/api/alerts").json["data"]
    assert len([a for a in active if a["item_id"] == item["id"]]) == 1


def test_two_big_shipments_only_one_wins(app, client, make_item):
    item = make_item(reorder_threshold=0, initial_stock=5)

    def ship(_):
        return app.test_client().post(f"/api/items/{item['id']}/transactions",
                                      json={"type": "shipped", "quantity_change": -3, "created_by": "bot"}).status_code

    assert sorted(run_parallel(2, ship)) == [201, 409]
    assert client.get(f"/api/items/{item['id']}").json["current_stock"] == 2


def test_parallel_threshold_changes_and_shipments_keep_one_active_alert(app, client, make_item):
    item = make_item(reorder_threshold=5, initial_stock=40)

    def work(i):
        c = app.test_client()
        if i % 2:
            return c.patch(f"/api/items/{item['id']}", json={"reorder_threshold": 50 if i % 4 == 1 else 1}).status_code
        return c.post(f"/api/items/{item['id']}/transactions",
                      json={"type": "shipped", "quantity_change": -1, "created_by": "bot"}).status_code

    assert set(run_parallel(16, work)) <= {200, 201}
    statuses = [a["status"] for a in client.get("/api/alerts?status=open,acknowledged&page_size=100").json["data"]
                if a["item_id"] == item["id"]]
    assert len(statuses) <= 1


def test_parallel_duplicate_sku_creates_exactly_one(app, client):
    def create(_):
        return app.test_client().post("/api/items", json={"sku": "RACE-1", "name": "n", "unit": "u",
                                                          "reorder_threshold": 0}).status_code

    codes = run_parallel(8, create)
    assert codes.count(201) == 1 and codes.count(409) == 7


def test_parallel_retries_with_same_idempotency_key_record_once(app, client, make_item):
    item = make_item(reorder_threshold=0, initial_stock=10)

    def ship(_):
        return app.test_client().post(f"/api/items/{item['id']}/transactions",
                                      json={"type": "shipped", "quantity_change": -2, "created_by": "bot"},
                                      headers={"Idempotency-Key": "retry-me"}).status_code

    codes = run_parallel(6, ship)
    assert codes.count(201) == 1 and codes.count(200) == 5
    assert client.get(f"/api/items/{item['id']}").json["current_stock"] == 8

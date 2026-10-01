"""FR-4: alert lifecycle, and the answers to the open questions."""
import pytest

from app.db import Database, DuplicateKeyError


def alerts_for(client, item_id, status="open,acknowledged,resolved"):
    return [a for a in client.get(f"/api/alerts?status={status}&page_size=100").json["data"] if a["item_id"] == item_id]


def test_alert_opens_when_stock_drops_below_threshold(client, make_item, move, notifier):
    item = make_item(reorder_threshold=10, initial_stock=12)
    assert move(item["id"], "shipped", -2).json["alert_change"] is None  # 10 == threshold: not low
    res = move(item["id"], "shipped", -1)  # 9 < 10
    assert res.json["alert_change"]["action"] == "opened"
    alert = res.json["item"]["active_alert"]
    assert (alert["status"], alert["triggered_stock"], alert["threshold_at_trigger"]) == ("open", 9, 10)
    assert [a["id"] for a in notifier.opened] == [alert["id"]]


def test_new_item_with_no_stock_opens_alert_immediately(make_item):
    item = make_item(reorder_threshold=5)
    assert item["active_alert"]["status"] == "open"


def test_further_drops_do_not_create_duplicates(client, make_item, move, notifier):
    item = make_item(reorder_threshold=10, initial_stock=20)
    for _ in range(4):
        move(item["id"], "shipped", -4)
    assert len(alerts_for(client, item["id"])) == 1
    assert len(notifier.opened) == 1


def test_acknowledge_then_recover_resolves(client, make_item, move):
    item = make_item(reorder_threshold=10, initial_stock=5)
    alert_id = item["active_alert"]["id"]
    res = client.post(f"/api/alerts/{alert_id}/acknowledge", json={"acknowledged_by": "Lee"})
    assert res.status_code == 200
    assert (res.json["status"], res.json["acknowledged_by"]) == ("acknowledged", "Lee")
    assert res.json["acknowledged_at"]
    # Acknowledging twice is a harmless no-op (double clicks, retries).
    assert client.post(f"/api/alerts/{alert_id}/acknowledge").json["status"] == "acknowledged"
    # Dropping further while acknowledged: still only one active alert.
    move(item["id"], "shipped", -1)
    assert len(alerts_for(client, item["id"], "open,acknowledged")) == 1
    # Back to exactly the threshold resolves it.
    res = move(item["id"], "received", 6)
    assert res.json["alert_change"] == {"action": "resolved", "alert_id": alert_id}
    resolved = alerts_for(client, item["id"], "resolved")[0]
    assert (resolved["resolution_reason"], resolved["resolved_stock"]) == ("stock_recovered", 10)
    assert res.json["item"]["active_alert"] is None


def test_recover_then_drop_again_creates_a_new_alert(client, make_item, move):
    item = make_item(reorder_threshold=10, initial_stock=5)
    first = item["active_alert"]["id"]
    move(item["id"], "received", 10)
    res = move(item["id"], "shipped", -8)
    assert res.json["alert_change"]["action"] == "opened"
    assert res.json["alert_change"]["alert_id"] != first
    statuses = sorted(a["status"] for a in alerts_for(client, item["id"]))
    assert statuses == ["open", "resolved"]


def test_threshold_change_reevaluates_immediately(client, make_item):
    item = make_item(reorder_threshold=5, initial_stock=8)
    assert item["active_alert"] is None
    raised = client.patch(f"/api/items/{item['id']}", json={"reorder_threshold": 9}).json
    assert raised["active_alert"]["status"] == "open"
    lowered = client.patch(f"/api/items/{item['id']}", json={"reorder_threshold": 8}).json
    assert lowered["active_alert"] is None
    assert alerts_for(client, item["id"], "resolved")[0]["resolution_reason"] == "threshold_changed"


def test_threshold_zero_means_never_alert(client, make_item, move):
    item = make_item(reorder_threshold=0, initial_stock=1)
    move(item["id"], "shipped", -1)
    assert alerts_for(client, item["id"]) == []


def test_archiving_resolves_alert_and_restoring_reevaluates(client, make_item):
    item = make_item(reorder_threshold=10, initial_stock=3)
    archived = client.patch(f"/api/items/{item['id']}", json={"is_archived": True}).json
    assert archived["active_alert"] is None
    assert alerts_for(client, item["id"], "resolved")[0]["resolution_reason"] == "item_archived"
    restored = client.patch(f"/api/items/{item['id']}", json={"is_archived": False}).json
    assert restored["active_alert"]["status"] == "open"


def test_acknowledge_errors(client, make_item, move):
    assert client.post("/api/alerts/999/acknowledge").status_code == 404
    item = make_item(reorder_threshold=10, initial_stock=5)
    alert_id = item["active_alert"]["id"]
    move(item["id"], "received", 50)
    res = client.post(f"/api/alerts/{alert_id}/acknowledge")
    assert res.status_code == 409 and res.json["error"]["code"] == "ALERT_RESOLVED"


def test_alert_list_filters_and_summary(client, make_item):
    a = make_item(reorder_threshold=10, initial_stock=1)
    make_item(reorder_threshold=10, initial_stock=2)
    make_item(reorder_threshold=1, initial_stock=50)
    client.post(f"/api/alerts/{a['active_alert']['id']}/acknowledge")
    assert client.get("/api/alerts/summary").json == {"open": 1, "acknowledged": 1}
    default = client.get("/api/alerts").json
    assert default["total"] == 2
    assert default["data"][0]["item"]["sku"].startswith("TEST-")
    assert client.get("/api/alerts?status=resolved").json["total"] == 0
    assert client.get("/api/alerts?status=bogus").status_code == 422


def test_database_refuses_a_second_active_alert(database_url, make_item):
    """The UNIQUE index on the generated column backs up the application rule."""
    item = make_item(reorder_threshold=10)  # already has an open alert
    db = Database(database_url)
    conn = db.connect()
    try:
        with pytest.raises(DuplicateKeyError) as info:
            with db.transaction(conn) as tx:
                tx.execute("INSERT INTO alerts (item_id, status, triggered_stock, threshold_at_trigger)"
                           " VALUES (:id, 'acknowledged', 0, 10)", {"id": item["id"]})
        assert info.value.constraint == "uq_alerts_one_active_per_item"
    finally:
        conn.close()

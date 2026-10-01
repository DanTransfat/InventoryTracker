"""FR-1 (manage items) and FR-3 (view stock) plus API conventions."""


def test_create_item_returns_201_with_location_and_normalised_sku(client):
    res = client.post("/api/items", json={"sku": " ab-100 ", "name": "Widget", "description": "Blue",
                                          "unit": "each", "reorder_threshold": 5})
    assert res.status_code == 201
    assert res.headers["Location"] == f"/api/items/{res.json['id']}"
    body = res.json
    assert body["sku"] == "AB-100"
    assert body["current_stock"] == 0
    assert body["is_archived"] is False
    assert body["created_at"].endswith("Z")


def test_duplicate_sku_is_409_with_field_error(client, make_item):
    make_item(sku="DUP-1")
    res = client.post("/api/items", json={"sku": "dup-1", "name": "Other", "unit": "each", "reorder_threshold": 1})
    assert res.status_code == 409
    assert res.json["error"]["code"] == "DUPLICATE_SKU"
    assert "sku" in res.json["error"]["fields"]


def test_validation_errors_are_422_with_per_field_messages(client):
    res = client.post("/api/items", json={"sku": "bad sku!", "unit": "", "reorder_threshold": -1, "color": "red"})
    assert res.status_code == 422
    err = res.json["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert set(err["fields"]) >= {"sku", "name", "unit", "reorder_threshold", "color"}


def test_threshold_must_be_whole_number(client):
    for bad in (2.5, "7", True):
        res = client.post("/api/items", json={"sku": "X1", "name": "n", "unit": "u", "reorder_threshold": bad})
        assert res.status_code == 422, bad


def test_malformed_json_is_400(client):
    res = client.post("/api/items", data="{not json", content_type="application/json")
    assert res.status_code == 400
    assert res.json["error"]["code"] == "INVALID_JSON"


def test_unknown_item_is_404_json(client):
    res = client.get("/api/items/9999")
    assert res.status_code == 404
    assert res.json["error"]["code"] == "ITEM_NOT_FOUND"
    assert client.get("/api/nope").json["error"]["code"] == "NOT_FOUND"


def test_edit_item_fields(client, make_item):
    item = make_item()
    res = client.patch(f"/api/items/{item['id']}", json={"name": "Renamed", "description": "d",
                                                         "unit": "box", "reorder_threshold": 3})
    assert res.status_code == 200
    assert (res.json["name"], res.json["unit"], res.json["reorder_threshold"]) == ("Renamed", "box", 3)


def test_sku_is_immutable(client, make_item):
    item = make_item()
    res = client.patch(f"/api/items/{item['id']}", json={"sku": "NEW"})
    assert res.status_code == 422
    assert res.json["error"]["code"] == "SKU_IMMUTABLE"


def test_null_for_required_field_is_rejected(client, make_item):
    item = make_item()
    res = client.patch(f"/api/items/{item['id']}", json={"name": None})
    assert res.status_code == 422
    assert "name" in res.json["error"]["fields"]


def test_archive_hides_item_but_keeps_history(client, make_item, move):
    item = make_item(reorder_threshold=0)
    move(item["id"], "received", 5)
    res = client.patch(f"/api/items/{item['id']}", json={"is_archived": True})
    assert res.json["is_archived"] is True and res.json["archived_at"]
    listed = client.get("/api/items").json
    assert all(i["id"] != item["id"] for i in listed["data"])
    with_archived = client.get("/api/items?include_archived=true").json
    assert any(i["id"] == item["id"] for i in with_archived["data"])
    assert client.get(f"/api/items/{item['id']}/transactions").json["total"] == 1
    # Restoring brings it back.
    client.patch(f"/api/items/{item['id']}", json={"is_archived": False})
    assert any(i["id"] == item["id"] for i in client.get("/api/items").json["data"])


def test_initial_stock_is_recorded_as_a_ledger_entry(client, make_item):
    item = make_item(initial_stock=12, created_by="Dana")
    assert item["current_stock"] == 12
    history = client.get(f"/api/items/{item['id']}/transactions").json["data"]
    assert len(history) == 1
    assert history[0]["type"] == "received" and history[0]["quantity_change"] == 12
    assert history[0]["created_by"] == "Dana"


def test_list_search_filter_sort_and_paginate(client, make_item, move):
    a = make_item(sku="ALPHA-1", name="Copper wire", reorder_threshold=5, initial_stock=50)
    b = make_item(sku="BETA-1", name="Steel wire", reorder_threshold=5, initial_stock=2)
    c = make_item(sku="GAMMA-1", name="Rope", reorder_threshold=5, initial_stock=5)

    assert [i["sku"] for i in client.get("/api/items?search=beta").json["data"]] == ["BETA-1"]
    assert {i["sku"] for i in client.get("/api/items?search=WIRE").json["data"]} == {"ALPHA-1", "BETA-1"}
    # Wildcards in search text are literal.
    assert client.get("/api/items?search=%25").json["total"] == 0

    low = client.get("/api/items?low_stock=true").json
    assert [i["sku"] for i in low["data"]] == ["BETA-1"]
    assert low["data"][0]["is_low_stock"] is True

    by_stock = client.get("/api/items?sort=-current_stock").json["data"]
    assert [i["current_stock"] for i in by_stock] == [50, 5, 2]
    by_sku = client.get("/api/items?sort=sku").json["data"]
    assert [i["sku"] for i in by_sku] == ["ALPHA-1", "BETA-1", "GAMMA-1"]

    page2 = client.get("/api/items?sort=sku&page=2&page_size=2").json
    assert (page2["total"], page2["total_pages"], page2["page"]) == (3, 2, 2)
    assert [i["sku"] for i in page2["data"]] == ["GAMMA-1"]
    assert c["is_low_stock"] is False  # equal to threshold is not low


def test_list_rejects_bad_query_params(client):
    assert client.get("/api/items?sort=price").status_code == 422
    assert client.get("/api/items?page=0").status_code == 422
    assert client.get("/api/items?page_size=500").status_code == 422
    assert client.get("/api/items?page=abc").status_code == 422


def test_cors_headers_for_allowed_origin(client):
    res = client.get("/api/items", headers={"Origin": "http://localhost:5173"})
    assert res.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Access-Control-Allow-Origin" not in client.get("/api/items", headers={"Origin": "http://evil.test"}).headers

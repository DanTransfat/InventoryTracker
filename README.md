# InventoryTracker

A small-warehouse inventory app with a stock **ledger** and automatic **low-stock alerts**.

- **Frontend:** React 19 + TypeScript, built with Vite
- **Backend:** Python 3.10+ / Flask, Pydantic for validation, raw SQL through PyMySQL
- **Database:** MySQL 8, schema managed by versioned SQL migrations

```
inventory-tracker/
├── docker-compose.yml        MySQL + API + web in one command
├── .env.example              every setting, shared by Compose, Flask and Vite
├── backend/
│   ├── app/
│   │   ├── api/routes.py     HTTP layer: parse request → call service → JSON
│   │   ├── services/         business rules (ledger, alert lifecycle, idempotency)
│   │   ├── repositories/     data access: SQL only, no rules
│   │   ├── db.py             connections, transactions, deadlock retry, migration runner
│   │   ├── schemas.py        request validation (Pydantic)
│   │   └── errors.py         one error type → consistent JSON error body
│   ├── migrations/mysql/     versioned schema (the production source of truth)
│   ├── migrations/sqlite/    mirror used only by the fast test suite
│   ├── scripts/              migrate.py, seed.py
│   └── tests/                53 tests incl. concurrency
└── frontend/src/
    ├── pages/                Inventory list, Item detail, New item, Alerts
    ├── components/           forms, chart, shared UI states
    └── lib/                  API client, tiny data layer, tiny router
```

---

## 1. Run it

### Option A — Docker (recommended, ~3 minutes)

Requires Docker Desktop (or Docker Engine with the Compose plugin).

```bash
git clone <this repo> inventory-tracker && cd inventory-tracker
cp .env.example .env            # edit the passwords if you like
docker compose up --build
```

Open **http://localhost:8080**. The backend container waits for MySQL, applies migrations,
loads 60 seeded items (13 of them below threshold), then starts. The API is also exposed
directly at http://localhost:8000/api.

Reset everything: `docker compose down -v` (the `-v` deletes the MySQL volume).

### Deploy to a server

One command on a fresh Ubuntu VM sets up Docker, HTTPS and the app. See
**[deploy/README.md](deploy/README.md)**.

### Option B — run the pieces yourself

Requires Python 3.10+, Node 20+, and a MySQL 8 server.

```bash
cp .env.example .env
# Point DATABASE_URL in .env at your MySQL. To use only Docker for the database:
docker compose up -d mysql

# Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m scripts.migrate
python -m scripts.seed
python wsgi.py                                          # http://localhost:8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                                             # http://localhost:5173
```

If you bring your own MySQL instead, create the database first:

```sql
CREATE DATABASE inventory CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'inventory'@'%' IDENTIFIED BY 'change-me';
GRANT ALL ON inventory.* TO 'inventory'@'%';
-- The migration creates triggers. With binary logging on (the MySQL 8 default), a
-- non-SUPER user needs this, or run the migration as root:
SET GLOBAL log_bin_trust_function_creators = 1;
```

### Tests

```bash
cd backend
pytest                                    # SQLite, ~3 s, no server needed
TEST_DATABASE_URL=mysql://root:change-me-root@127.0.0.1:3307/inventory_test pytest   # real MySQL 8
```

For the MySQL run, create the empty `inventory_test` database first; the suite drops and
re-migrates its tables before every test. CI (`.github/workflows/ci.yml`) runs both, plus a
clean migrate + seed on an empty MySQL 8 database, and the frontend type-check and build.

```bash
cd frontend && npm run typecheck && npm run build
```

---

## 2. Framework and library choices

| Choice | Why |
|---|---|
| **Flask** | Small and explicit. Each route is a few lines that hand off to the service layer, so the interesting code (locking, ledger, alerts) is easy to find. FastAPI would also be a good fit; its main extra is auto-generated docs, which this README covers instead. |
| **Raw SQL via PyMySQL** (no ORM) | The concurrency guarantees depend on exact SQL: `SELECT … FOR UPDATE`, isolation level, constraint names. Writing it directly keeps that visible and reviewable. Repositories hold all SQL so it is still in one place. |
| **Pydantic** | Declarative request validation with precise per-field errors, which the UI shows next to the input. `StrictInt` rejects `2.5`, `"7"` and `true` as quantities. |
| **Versioned `.sql` migrations + 50-line runner** | The schema is plain MySQL DDL anyone can read. Applied files are recorded in `schema_migrations`, so re-running is a no-op. |
| **React + TypeScript + Vite** | Required stack (React), TS for safety, Vite for a fast dev server with an `/api` proxy. |
| **No router / data-fetching libraries** | The app has four views. A 50-line router (`lib/router.tsx`) and an 80-line query hook with tag-based invalidation (`lib/query.ts`) cover what's needed, with no dependency weight. In a larger app I would use React Router and TanStack Query, which this code deliberately mimics. |
| **Plain CSS** | Visual polish isn't the focus; one stylesheet with CSS variables is enough. |
| **nginx** (Docker) | Serves the built frontend and proxies `/api` to Flask so the browser sees one origin. |

---

## 3. Data model

```
items                       stock_transactions (append-only ledger)     alerts
─────                       ──────────────────                          ──────
id                          id                                          id
sku  (UNIQUE)               item_id → items.id                          item_id → items.id
name, description, unit     type: received|shipped|adjustment|returned  status: open|acknowledged|resolved
reorder_threshold ≥ 0       quantity_change ≠ 0 (signed)                triggered_stock, threshold_at_trigger
current_stock ≥ 0  (cache)  balance_after ≥ 0                           created/acknowledged/resolved_at
is_archived, archived_at    note, created_by, created_at                acknowledged_by, resolution_reason
is_low_stock (generated)    idempotency_key (UNIQUE, nullable)          active_item_id (generated, UNIQUE)
created_at, updated_at
```

**Stock comes from the ledger.** Every change is a `stock_transactions` row. `items.current_stock`
is a cache of `SUM(quantity_change)`, and each row also stores `balance_after` (handy for the
history chart). The cache is written only in the same database transaction that inserts the
ledger row, while that item's row is locked, so they cannot drift apart.
`GET /api/integrity/ledger` recomputes every item from the ledger and lists any mismatches
(the tests assert it is always empty).

**Rules the database enforces on its own,** so even a bug or a manual SQL session can't break them:

- `UNIQUE (sku)`; foreign keys from transactions and alerts to items; `NOT NULL` throughout.
- `CHECK (current_stock >= 0)`, `CHECK (balance_after >= 0)`, `CHECK (quantity_change <> 0)`.
- `CHECK` that the sign matches the type (received/returned > 0, shipped < 0).
- Triggers that reject any `UPDATE` or `DELETE` on `stock_transactions`.
- At most one active alert per item: `active_item_id` is a generated column equal to
  `item_id` while the alert is open/acknowledged and `NULL` once resolved. A `UNIQUE` index on
  it allows any number of resolved alerts (NULLs) but only one active one. This stands in
  for a partial unique index, which MySQL doesn't have.

**Indexes for the list page.** The list always filters `is_archived = 0`, so composite
indexes lead with it: `(is_archived, name)`, `(is_archived, sku)`, `(is_archived, current_stock)`.
"Low stock" compares two columns (`current_stock < reorder_threshold`), which no index can
serve, so it is materialised as the stored generated column `is_low_stock` and indexed as
`(is_archived, is_low_stock, name)`. SKU search is a prefix match (`LIKE 'ABC%'`, index-friendly);
name search is a substring match (`LIKE '%wire%'`), which scans — fine at warehouse scale,
with a MySQL `FULLTEXT` index as the upgrade path.

---

## 4. Concurrency: how the guarantees hold

Requirement: two simultaneous shipments must never take stock below zero, must never
create two open alerts, and the transaction + alert update must be one database transaction.

Every write path in `services/inventory.py` follows the same recipe:

```
BEGIN                                    -- session runs at READ COMMITTED
SELECT ... FROM items WHERE id = ? FOR UPDATE    -- exclusive lock on this item's row
  check: archived? enough stock? idempotency key seen?
INSERT INTO stock_transactions (..., balance_after)
UPDATE items SET current_stock = ?
SELECT active alert for item; INSERT or resolve as the lifecycle rules say
COMMIT                                   -- or ROLLBACK on any error: nothing is saved
```

1. **The item row lock serialises writers per item.** If two shipments arrive together, the
   second blocks at `FOR UPDATE` until the first commits, then reads the *new* stock and is
   rejected with 409 if there isn't enough. Different items never wait on each other.
2. **Alert decisions happen under the same lock,** so two requests can't both see "no active
   alert" and both open one. The `UNIQUE (active_item_id)` index is a second, independent guard.
3. **One transaction, all or nothing.** A rejected shipment raises before anything is written,
   and any error rolls back the ledger row, the stock cache and the alert change together.
4. **READ COMMITTED, not MySQL's default REPEATABLE READ.** Locking reads always see the latest
   committed row either way, but REPEATABLE READ adds *gap locks* on index ranges, which can
   make writes to different items deadlock. Correctness here comes from row locks, so the
   weaker level is safe and avoids that class of deadlock.
5. **Consistent lock order.** Paths that touch both take the item lock before touching
   alerts; acknowledging an alert touches only the alert row (with a conditional
   `UPDATE … WHERE status = 'open'`). With no cycles, deadlocks shouldn't happen; if InnoDB
   still reports one (1213) or a lock-wait timeout (1205), `db.run_in_transaction` retries the
   whole transaction up to three times.
6. **Duplicate SKU races** are settled by the unique index: the losing `INSERT` gets error 1062,
   mapped to 409 `DUPLICATE_SKU`.

`tests/test_concurrency.py` fires 20 parallel shipments of 1 at an item holding 10 and
checks that exactly 10 succeed, stock ends at 0, the ledger reconciles and there is one alert.
It also races threshold changes against shipments, duplicate SKUs and retried idempotency keys.
(On SQLite the same guarantee comes from `BEGIN IMMEDIATE`, a database-wide write lock; I
checked the shipment test fails if that is weakened to a plain `BEGIN`.)

---

## 5. Answers to the open questions

1. **Can an item start with stock?** Yes, through an optional `initial_stock` on create. It is
   recorded as a `received` ledger entry ("Opening balance") in the same transaction, never
   written directly to the stock column, so the ledger stays complete. This saves a second step
   for the very common "new item, and here's what's on the shelf" case.
2. **Open alert when its item is archived?** It is resolved with reason `item_archived`. An
   archived item is hidden and can't take stock movements, so an alert nobody can act on would
   only inflate the count. Restoring the item re-evaluates it and opens a fresh alert if it is
   still low. Recording movements on an archived item returns 409 `ITEM_ARCHIVED`.
3. **Stock exactly equal to the threshold — low in the UI?** No. "Low" has one definition
   everywhere: `stock < threshold`, the same test that opens an alert. Two definitions would mean
   rows highlighted red with no alert behind them, which is confusing. Think of the threshold
   as "the minimum we're happy holding".
4. **Can an adjustment go below zero?** No. The no-negative rule applies to every transaction
   type; physical stock can't be negative, and a `CHECK` on `current_stock` backs it up.
   An over-count is corrected with a negative adjustment down to zero at most.
5. **Threshold zero = never alert?** Yes. Since stock can't go below 0, `stock < 0` is never true,
   so it falls out of the rule with no special case. Useful for discontinued or made-to-order items.
6. **Recovered, then dropped again — new alert or reopened?** A new alert. The resolved one
   stays in history with its own timestamps and reason, so the history shows each low-stock
   episode separately ("we ran low three times this quarter") instead of overwriting it.

Other decisions worth knowing:

- **SKUs** are trimmed and stored upper-case (`ab-1` → `AB-1`) so uniqueness doesn't depend on
  database collation. Allowed: letters, digits, `.`, `_`, `-`, up to 64 characters.
- **Acknowledging** an already-acknowledged alert is a no-op 200 (double clicks are harmless);
  acknowledging a resolved alert is 409 `ALERT_RESOLVED`.
- A **new item with 0 stock and a positive threshold** opens an alert immediately — it is below threshold.
- **Changing the threshold** re-evaluates instantly and can open or resolve an alert
  (resolution reason `threshold_changed`).
- The **header count** shows *open* alerts only (acknowledged ones are already being handled).

---

## 6. API

Base path `/api`. JSON in and out. All validation is enforced on the server.

| Method & path | Purpose | Success |
|---|---|---|
| `GET /items` | List items. Query: `search`, `low_stock=true`, `include_archived=true`, `sort=name\|sku\|current_stock` (prefix `-` for descending), `page`, `page_size` (≤100) | 200 page |
| `POST /items` | Create: `sku`, `name`, `unit`, `reorder_threshold`, optional `description`, `initial_stock`, `created_by` | 201 item + `Location` |
| `GET /items/{id}` | Item with current stock and `active_alert` | 200 |
| `PATCH /items/{id}` | Any of `name`, `description`, `unit`, `reorder_threshold`, `is_archived` (`sku` → 422 `SKU_IMMUTABLE`) | 200 item |
| `GET /items/{id}/transactions` | Ledger, newest first, paginated | 200 page |
| `POST /items/{id}/transactions` | `type`, signed `quantity_change`, `created_by`, optional `note`. Optional `Idempotency-Key` header | 201 `{transaction, item, alert_change}` (200 on idempotent replay) |
| `GET /items/{id}/stock-history` | Balance after each movement, oldest first (chart) | 200 |
| `GET /alerts` | `status=open,acknowledged` (default) or `resolved`, paginated | 200 page |
| `GET /alerts/summary` | `{open, acknowledged}` counts for the header | 200 |
| `POST /alerts/{id}/acknowledge` | Optional `acknowledged_by` | 200 alert |
| `GET /health`, `GET /integrity/ledger` | Liveness (touches the DB); ledger reconciliation | 200 |

Pages look like `{"data": [...], "page": 1, "page_size": 25, "total": 60, "total_pages": 3}`.

**Errors** always look like this:

```json
{"error": {"code": "INSUFFICIENT_STOCK",
           "message": "Insufficient stock: 4 box on hand, cannot remove 5.",
           "fields": {"quantity_change": "Only 4 on hand."},
           "details": {"current_stock": 4, "requested_change": -5}}}
```

| Status | Codes |
|---|---|
| 400 | `INVALID_JSON` |
| 404 | `ITEM_NOT_FOUND`, `ALERT_NOT_FOUND`, `NOT_FOUND` |
| 409 | `DUPLICATE_SKU`, `INSUFFICIENT_STOCK`, `ITEM_ARCHIVED`, `ALERT_RESOLVED`, `IDEMPOTENCY_KEY_REUSED` |
| 422 | `VALIDATION_ERROR` (with `fields`), `SKU_IMMUTABLE` |

Quick try:

```bash
curl -s localhost:8000/api/items?low_stock=true | jq '.data[] | {sku, current_stock, reorder_threshold}'
curl -s -X POST localhost:8000/api/items/1/transactions \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-1' \
  -d '{"type":"shipped","quantity_change":-2,"created_by":"me"}'
```

---

## 7. Frontend behaviour

- **Every fetch** shows a loading state, an empty state and an error state with a retry button.
- **Server errors appear next to the field** they belong to (`DUPLICATE_SKU` under the SKU box,
  `INSUFFICIENT_STOCK` under the quantity) plus a summary above the form.
- **No full reloads:** after a mutation the code calls `invalidate("item:7", "items", "alerts")`.
  Every mounted query with one of those tags refetches in the background, so the stock figure,
  history, chart, list and header badge all update together.
- **Double-submit protection:** submit buttons disable while a request is in flight, and stock
  movements also send an `Idempotency-Key`, so a retried request after a lost response is
  recognised by the server rather than recorded twice.
- **URL state:** the list's search, low-stock filter, sort and page live in the query string
  (`/?q=tape&low=1&sort=-current_stock&page=2`), so views can be bookmarked and shared, and
  back/forward work. Typing in search is debounced 300 ms and replaces (not pushes) history.
- The quantity box takes a positive number; the type (and, for adjustments, the direction)
  decides the sign sent to the API, which keeps the form hard to misuse.

---

## 8. Stretch goals

| Goal | State |
|---|---|
| Containerized setup | **Done.** `docker compose up --build` starts MySQL, API and web. |
| Deployment | **Done.** One-command HTTPS setup on a single server ([deploy/README.md](deploy/README.md)), smoke-tested in CI. |
| Idempotent transaction creation | **Done.** `Idempotency-Key` header; same key + same body replays the original (200), same key + different body is 409. Checked under the item lock and backed by a unique index. |
| Stock history chart | **Done.** SVG step chart on the item page, from `balance_after`, with the threshold line. |
| Alert notifications | **Done (basic).** `AlertNotifier` interface with a log implementation (default) and a webhook implementation (`ALERT_NOTIFIER=webhook`). Sent after commit. |
| Live updates (SSE/websockets) | Not done. Updates are refetch-based; other browsers see changes on their next fetch. |
| Bulk CSV receiving | Not done. |

---

## 9. Known gaps and what I'd do next

- **Single-server deployment only.** One VM is a single point of failure. A larger setup
  would use managed MySQL with automated backups and run the API on two or more instances.
- **Notifications can be lost** if the process dies between commit and send. The durable fix
  is a transactional outbox: write a `notifications` row in the same transaction, deliver it
  from a background worker.
- **Pagination is offset-based.** Fine at this size; keyset pagination (`WHERE id < ?`) would
  keep deep pages fast for very long histories.
- **No authentication;** `created_by` is free text, as the brief allows.
- **One connection per request,** no pool. Adequate here; a pool (or SQLAlchemy's) would help
  under load.
- **The SQLite migration mirrors the MySQL one by hand.** It exists only for fast tests; CI runs
  the same suite on MySQL 8 to catch drift.
- **No frontend tests.** The backend suite covers the rules; a few Playwright flows would be next.
- **Idempotency keys never expire.** A production version would scope keys per client and
  expire them after a day.

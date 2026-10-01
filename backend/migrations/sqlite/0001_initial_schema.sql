-- 0001_initial_schema.sql  (SQLite 3.31+)
--
-- SQLite mirror of migrations/mysql/0001_initial_schema.sql. It exists so the
-- test suite can run in seconds with no server. MySQL is the production target;
-- keep the two files in lockstep (same tables, columns, constraints, indexes).

CREATE TABLE items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sku               TEXT    NOT NULL,
    name              TEXT    NOT NULL,
    description       TEXT    NOT NULL DEFAULT '',
    unit              TEXT    NOT NULL,
    reorder_threshold INTEGER NOT NULL,
    current_stock     INTEGER NOT NULL DEFAULT 0,
    is_archived       INTEGER NOT NULL DEFAULT 0,
    archived_at       DATETIME NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_low_stock      INTEGER GENERATED ALWAYS AS (current_stock < reorder_threshold) STORED,
    CONSTRAINT uq_items_sku UNIQUE (sku),
    CONSTRAINT ck_items_threshold_nonneg CHECK (reorder_threshold >= 0),
    CONSTRAINT ck_items_stock_nonneg     CHECK (current_stock >= 0)
);
CREATE INDEX ix_items_archived_name  ON items (is_archived, name);
CREATE INDEX ix_items_archived_sku   ON items (is_archived, sku);
CREATE INDEX ix_items_archived_stock ON items (is_archived, current_stock);
CREATE INDEX ix_items_archived_low   ON items (is_archived, is_low_stock, name);

CREATE TABLE stock_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id          INTEGER NOT NULL REFERENCES items (id) ON DELETE RESTRICT,
    type             TEXT    NOT NULL CHECK (type IN ('received','shipped','adjustment','returned')),
    quantity_change  INTEGER NOT NULL,
    balance_after    INTEGER NOT NULL,
    note             TEXT    NULL,
    created_by       TEXT    NOT NULL,
    idempotency_key  TEXT    NULL,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_txn_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT ck_txn_nonzero        CHECK (quantity_change <> 0),
    CONSTRAINT ck_txn_balance_nonneg CHECK (balance_after >= 0),
    CONSTRAINT ck_txn_sign_matches_type CHECK (
        (type IN ('received','returned') AND quantity_change > 0)
        OR (type = 'shipped' AND quantity_change < 0)
        OR (type = 'adjustment')
    )
);
CREATE INDEX ix_txn_item_id ON stock_transactions (item_id, id);

CREATE TRIGGER trg_stock_transactions_no_update BEFORE UPDATE ON stock_transactions
BEGIN SELECT RAISE(ABORT, 'stock_transactions is append-only'); END;

CREATE TRIGGER trg_stock_transactions_no_delete BEFORE DELETE ON stock_transactions
BEGIN SELECT RAISE(ABORT, 'stock_transactions is append-only'); END;

CREATE TABLE alerts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id              INTEGER NOT NULL REFERENCES items (id) ON DELETE RESTRICT,
    status               TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
    triggered_stock      INTEGER NOT NULL,
    threshold_at_trigger INTEGER NOT NULL,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at      DATETIME NULL,
    acknowledged_by      TEXT    NULL,
    resolved_at          DATETIME NULL,
    resolution_reason    TEXT    NULL,
    resolved_stock       INTEGER NULL,
    active_item_id       INTEGER GENERATED ALWAYS AS (
        CASE WHEN status IN ('open','acknowledged') THEN item_id ELSE NULL END
    ) STORED,
    CONSTRAINT uq_alerts_one_active_per_item UNIQUE (active_item_id)
);
CREATE INDEX ix_alerts_status_created ON alerts (status, created_at);
CREATE INDEX ix_alerts_item ON alerts (item_id, id);

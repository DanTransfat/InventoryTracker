-- 0001_initial_schema.sql  (MySQL 8.0.16+; CHECK constraints are enforced from 8.0.16)
--
-- Design notes
--   * items.current_stock is a CACHE of SUM(stock_transactions.quantity_change).
--     It is only ever written in the same DB transaction that inserts a ledger row,
--     while holding a row lock on the item, so the two can never disagree.
--   * stock_transactions is append-only (enforced by triggers below).
--   * alerts.active_item_id is a generated column that is NULL unless the alert is
--     open/acknowledged. A UNIQUE index on it makes "at most one active alert per item"
--     a database guarantee, not just an application rule (MySQL has no partial indexes,
--     and UNIQUE allows any number of NULLs).

CREATE TABLE items (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    sku               VARCHAR(64)     NOT NULL,
    name              VARCHAR(200)    NOT NULL,
    description       VARCHAR(2000)   NOT NULL DEFAULT '',
    unit              VARCHAR(32)     NOT NULL,
    reorder_threshold INT             NOT NULL,
    current_stock     INT             NOT NULL DEFAULT 0,
    is_archived       TINYINT(1)      NOT NULL DEFAULT 0,
    archived_at       DATETIME(6)     NULL,
    created_at        DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at        DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    -- Comparing two columns cannot use an index, so we materialise the result.
    is_low_stock      TINYINT(1) AS (current_stock < reorder_threshold) STORED,
    PRIMARY KEY (id),
    UNIQUE KEY uq_items_sku (sku),
    KEY ix_items_archived_name  (is_archived, name),
    KEY ix_items_archived_sku   (is_archived, sku),
    KEY ix_items_archived_stock (is_archived, current_stock),
    KEY ix_items_archived_low   (is_archived, is_low_stock, name),
    CONSTRAINT ck_items_threshold_nonneg CHECK (reorder_threshold >= 0),
    CONSTRAINT ck_items_stock_nonneg     CHECK (current_stock >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE stock_transactions (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    item_id          BIGINT UNSIGNED NOT NULL,
    type             ENUM('received','shipped','adjustment','returned') NOT NULL,
    quantity_change  INT             NOT NULL,
    balance_after    INT             NOT NULL,
    note             VARCHAR(500)    NULL,
    created_by       VARCHAR(100)    NOT NULL,
    idempotency_key  VARCHAR(100)    NULL,
    created_at       DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_txn_idempotency_key (idempotency_key),
    KEY ix_txn_item_id (item_id, id),
    CONSTRAINT fk_txn_item FOREIGN KEY (item_id) REFERENCES items (id) ON DELETE RESTRICT,
    CONSTRAINT ck_txn_nonzero        CHECK (quantity_change <> 0),
    CONSTRAINT ck_txn_balance_nonneg CHECK (balance_after >= 0),
    CONSTRAINT ck_txn_sign_matches_type CHECK (
        (type IN ('received','returned') AND quantity_change > 0)
        OR (type = 'shipped' AND quantity_change < 0)
        OR (type = 'adjustment')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- The ledger is append-only: corrections are new 'adjustment' rows.
CREATE TRIGGER trg_stock_transactions_no_update BEFORE UPDATE ON stock_transactions
FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock_transactions is append-only';

CREATE TRIGGER trg_stock_transactions_no_delete BEFORE DELETE ON stock_transactions
FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock_transactions is append-only';

CREATE TABLE alerts (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    item_id             BIGINT UNSIGNED NOT NULL,
    status              ENUM('open','acknowledged','resolved') NOT NULL DEFAULT 'open',
    triggered_stock     INT          NOT NULL,
    threshold_at_trigger INT         NOT NULL,
    created_at          DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    acknowledged_at     DATETIME(6)  NULL,
    acknowledged_by     VARCHAR(100) NULL,
    resolved_at         DATETIME(6)  NULL,
    resolution_reason   VARCHAR(32)  NULL,
    resolved_stock      INT          NULL,
    active_item_id      BIGINT UNSIGNED AS (
        CASE WHEN status IN ('open','acknowledged') THEN item_id ELSE NULL END
    ) STORED,
    PRIMARY KEY (id),
    UNIQUE KEY uq_alerts_one_active_per_item (active_item_id),
    KEY ix_alerts_status_created (status, created_at),
    KEY ix_alerts_item (item_id, id),
    CONSTRAINT fk_alert_item FOREIGN KEY (item_id) REFERENCES items (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

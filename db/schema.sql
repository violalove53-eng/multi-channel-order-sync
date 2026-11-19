-- Canonical order store for multi-channel-order-sync

CREATE TABLE IF NOT EXISTS orders (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,               -- 'tiktok' | 'shopify'
    source_order_id TEXT NOT NULL,
    buyer_name      TEXT,
    status          TEXT NOT NULL,               -- UNPAID | PAID | SHIPPED | DELIVERED | CANCELLED | REFUNDED
    total_amount    BIGINT NOT NULL,             -- minor units (cents), integer math only
    currency        TEXT NOT NULL DEFAULT 'USD',
    price_tier      NUMERIC(10, 2),              -- price-link tier for live-commerce orders
    created_at      TIMESTAMPTZ NOT NULL,
    paid_at         TIMESTAMPTZ,
    shipped_at      TIMESTAMPTZ,
    raw_payload     JSONB NOT NULL,              -- source record, verbatim
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_order_id)             -- the idempotency key
);

CREATE TABLE IF NOT EXISTS watermarks (
    source         TEXT PRIMARY KEY,
    last_synced_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    fetched     INT NOT NULL DEFAULT 0,
    inserted    INT NOT NULL DEFAULT 0,
    updated     INT NOT NULL DEFAULT 0,
    skipped     INT NOT NULL DEFAULT 0,
    failed      INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS failed_records (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    raw_payload  JSONB NOT NULL,
    error        TEXT NOT NULL,
    failed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);

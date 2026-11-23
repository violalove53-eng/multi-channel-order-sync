# Order Sync Project Spec

_Finalized 2026-11-18. Scope: order sync and nothing else._

## In One Sentence

Sync orders from TikTok Shop (about 700 orders) and a Shopify storefront into one unified order store of my own: build a solid pipeline first and hold off on features.

## Why This Project

- The data is real: the 700 orders came from my own shop and are not fabricated
- The shape is right: multi-source ingestion, schema mapping, idempotency, watermarks
- The trade-offs are grounded: every cut feature has a data-level reason (see "Design Decisions" at the end)

## Scope

**In scope:**
- TikTok order import (v1 uses CSV exports from Seller Center; the connector interface follows the standard shape, so the real API can replace it once access is approved)
- Shopify order sync (live GraphQL API connection; order volume is small, so it is used first to get the pipeline working)
- Unified order model + two schema mappings
- Idempotent writes, incremental watermarks, failure retries + dead letter, sync run logs

**Out of scope (deliberately cut, reasons at the end):**
- Automatic delisting to prevent overselling: price-link orders carry no product identity, so there is nothing to match on
- Order merging and reconciliation: TikTok Seller Center already provides these, so there is no need to rebuild them
- Reports / live-session analytics: left for v2, after the pipeline is finished

## Architecture

```
TikTok CSV ──► Connector(TikTok) ──┐
                                    ├──► Normalize (schema mapping) ──► Idempotent upsert ──► Order store (Postgres)
Shopify API ─► Connector(Shopify) ─┘                                              │
                                                            sync_runs log / failed_records (dead letter)
```

- **Connector interface** is a shared abstraction: `fetchOrders(since watermark) -> list of raw orders`. The TikTok implementation reads CSV, the Shopify implementation calls GraphQL, and upper layers don't see the difference
- **Normalize**: one mapping table per platform translates into the unified model; the full raw record is kept in `raw_payload`, so a wrong mapping can be replayed
- **Storage**: Postgres (SQLite is acceptable at the start, replaced before Milestone 2)

## Unified Order Model (Canonical Schema)

| Field | Description |
|---|---|
| `source` | `tiktok` / `shopify` |
| `source_order_id` | Original order ID on the platform |
| `buyer_name` | Buyer nickname |
| `status` | Unified enum: `UNPAID / PAID / SHIPPED / DELIVERED / CANCELLED / REFUNDED`; each platform's status terms map into it |
| `total_amount` | Stored in cents (integer) to avoid decimal precision issues |
| `currency` | USD |
| `price_tier` | Price tier (4.99 / 6.99 / …), specific to TikTok's price-link model; the original tier is preserved |
| `created_at / paid_at / shipped_at` | Timestamps, all UTC |
| `raw_payload` | Original platform data as JSON, kept for reference |

Unique key: `(source, source_order_id)`.

## Three Core Mechanisms

**1. Idempotency**
- Upsert by unique key: record doesn't exist → insert; exists and unchanged → skip; exists with an update → overwrite
- **No status regression**: the state machine only moves forward (`PAID → SHIPPED → DELIVERED`), so late, stale data cannot overwrite "shipped" back to "awaiting shipment"; `CANCELLED / REFUNDED` are terminal
- Acceptance criterion: running the same batch 3 times in a row produces identical row counts and contents

**2. Watermark**
- One watermark record per connector: `last_synced_at`
- Each run fetches only data after the watermark; it **deliberately rewinds 15 minutes as an overlap** to avoid missing orders at the boundary, and idempotency absorbs the resulting duplicates
- The watermark advances only after an entire batch is written successfully; after a mid-run crash, the next run refetches from the original watermark

**3. Failure Handling**
- One failed record doesn't take down the batch: it goes to the `failed_records` dead-letter table (raw data + error reason) while the rest sync normally
- API-side failures: retry with exponential backoff (Shopify rate limiting follows the throttle signals it returns)
- Each sync writes one `sync_runs` row: start/end time and fetched, inserted, skipped, updated and failed counts. This is the source of the run metrics

## Milestones (by Weekend)

- **W1 — Shopify end to end**: GraphQL fetch → mapping → idempotent write → incremental watermark. Low volume, focused on the pipeline
- **W2 — Full TikTok import**: export orders as CSV from Seller Center (finalize the second mapping table from real column names once a sample is available), import 700 orders, reconcile row counts
- **W3 — Robustness**: dead letter + retries + sync_runs logging; acceptance tests for three-run idempotency and resuming after interruption
- **W4 — Deliverables**: README (architecture diagram + one paragraph on each core mechanism) + 30-second demo + compiled numbers

## Tech Choices

- Language: Python, prioritizing speed; the language is not the point of the project
- DB: Postgres; deployment: eventually deploy a live demo
- No frontend; at most a minimal sync status page (reads sync_runs)

## Target Metrics (Compiled in W4)

Total orders (700+), duplicates blocked (how many are skipped on re-run), full-sync duration, and number of fields mapped in each of the two mapping tables.

## Design Decisions

1. Why overselling prevention was cut: price-link orders carry no product identity, so the data model sets the feature boundary
2. Why TikTok uses CSV: the practical reality of open API approval; the connector interface is designed to be swappable, so only the implementation layer changes once access is approved
3. Idempotency semantics: "The sync is idempotent: every order is keyed by a unique ID, and when the same order arrives again, we either skip it if nothing changed, or upsert it if it carries a newer state."

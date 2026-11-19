# multi-channel-order-sync

Sync orders from multiple sales channels into one canonical store.
Built on real data from my own shops: ~700 TikTok Shop orders (live-commerce, price-tier links) plus a young Shopify storefront.

**Scope: the sync pipeline only.** Idempotent writes, watermark-based incremental sync, per-source schema mapping. No dashboards, no reports — the pipeline is the product.

## Architecture

```
TikTok CSV ──► Connector(TikTok) ──┐
                                    ├──► Normalize (schema mapping) ──► Idempotent upsert ──► Postgres
Shopify API ─► Connector(Shopify) ─┘                                              │
                                                            sync_runs log / failed_records (dead letter)
```

Design notes: [docs/design.md](docs/design.md)

## Core mechanisms

- **Idempotent upsert** — every order is keyed by `(source, source_order_id)`. Re-running a sync skips unchanged records and upserts ones carrying a newer state. Order status is monotonic: a late, stale record can never move an order backwards.
- **Watermark incremental sync** — each connector stores a `last_synced_at` watermark and only fetches newer data, with a deliberate 15-minute overlap window. Overlap duplicates are absorbed by idempotency.
- **Schema mapping** — each source has one mapping table into the canonical order model. Raw payloads are stored verbatim (`raw_payload`) so mappings can be fixed and replayed.

## Numbers

_(to be filled in after the first full sync)_

- Total orders synced:
- Duplicates absorbed on re-run:
- Full-sync duration:

## Layout

```
connectors/   one connector per source (tiktok_csv, shopify_api)
core/         normalize, idempotent writer, watermark store
db/           schema.sql
docs/         design.md — full design notes
sample_data/  fake sample exports (real exports are gitignored, they contain buyer PII)
```

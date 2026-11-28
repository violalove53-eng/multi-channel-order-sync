from datetime import datetime, timedelta

from connectors.shopify_connector import ShopifyConnector
from connectors.shopify_mapping import map_shopify_order
from core.writer import write_orders

OVERLAP = timedelta(minutes=15)


def load_watermark(conn, source: str) -> datetime | None:
    # psycopg 3: conn.execute() opens a cursor internally and returns it, so .fetchone() can be chained
    row = conn.execute(
        "SELECT last_synced_at FROM watermarks WHERE source = %s",
        (source,),
    ).fetchone()
    return row[0] if row else None


def save_watermark(conn, source: str, last_synced_at: datetime) -> None:
    # EXCLUDED is the row we tried to insert, i.e. the new value
    conn.execute(
        """
        INSERT INTO watermarks (source, last_synced_at)
        VALUES (%s, %s)
        ON CONFLICT (source) DO UPDATE
            SET last_synced_at = EXCLUDED.last_synced_at
        """,
        (source, last_synced_at),
    )
    conn.commit()


def sync_shopify(conn, shopify: ShopifyConnector) -> None:
    # 1. Load the last saved watermark; None on the first run
    since = load_watermark(conn, "shopify")

    # 2. Query start: rewind 15 minutes so boundary orders aren't missed; no watermark means full sync
    query_since = since - OVERLAP if since is not None else None

    # 3. max_seen: the latest updatedAt seen in this batch, starting from the stored watermark
    max_seen = since

    # 4. Fetch orders: fetch_orders follows the cursor through every page (pagination branch)
    orders = shopify.fetch_orders(query_since)
    for order in orders:
        if max_seen is None or order.source_updated_at > max_seen:
            max_seen = order.source_updated_at

    # 5. Write orders to the orders table
    # Why the write must be idempotent: we can fetch the same order more than once.
    #   The 15-minute rewind re-fetches orders already written by the previous run,
    #   and a run that fails midway doesn't advance the watermark, so the next run re-fetches the whole batch.
    # write_orders upserts on (source, source_order_id), so duplicates from the rewind
    # or a retry update or skip the existing row instead of inserting a new one.
    # It commits once for the whole batch and rolls back if any row fails.
    write_orders(conn, [map_shopify_order(order) for order in orders])

    # 6. Only after the whole batch is written, save max_seen back to the watermarks table
    if max_seen is not None and max_seen != since:
        save_watermark(conn, "shopify", max_seen)

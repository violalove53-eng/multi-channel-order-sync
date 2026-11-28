"""Idempotent writer for the orders table.

Every order is keyed by (source, source_order_id). For each incoming order:
  - not in the table yet          -> insert
  - in the table, carries changes -> update, unless that would move status backwards
  - in the table, nothing changed -> skip

Status only moves forward (UNPAID -> PAID -> SHIPPED -> DELIVERED). CANCELLED and
REFUNDED are terminal: they can be reached from any status, and once there the
status never changes again.
"""

import json
from dataclasses import dataclass

from core.models import CanonicalOrder

FORWARD_STATUSES = ("UNPAID", "PAID", "SHIPPED", "DELIVERED")
TERMINAL_STATUSES = ("CANCELLED", "REFUNDED")

# The WHERE clause on DO UPDATE decides insert / update / skip in one statement:
#   - the update must be allowed by the status rules, and
#   - something must actually differ (otherwise it's a no-op and counts as skipped).
# When the WHERE is false Postgres returns no row, so an empty RETURNING = skipped.
# xmax = 0 on the returned row means it was freshly inserted rather than updated.
UPSERT_SQL = """
INSERT INTO orders (
    source, source_order_id, buyer_name, status, total_amount, currency,
    price_tier, created_at, paid_at, shipped_at, raw_payload
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (source, source_order_id) DO UPDATE SET
    buyer_name   = EXCLUDED.buyer_name,
    status       = EXCLUDED.status,
    total_amount = EXCLUDED.total_amount,
    currency     = EXCLUDED.currency,
    price_tier   = EXCLUDED.price_tier,
    created_at   = EXCLUDED.created_at,
    paid_at      = EXCLUDED.paid_at,
    shipped_at   = EXCLUDED.shipped_at,
    raw_payload  = EXCLUDED.raw_payload,
    last_seen_at = now()
WHERE (
        EXCLUDED.status = orders.status
        OR (
            orders.status NOT IN ('CANCELLED', 'REFUNDED')
            AND (
                EXCLUDED.status IN ('CANCELLED', 'REFUNDED')
                OR array_position(ARRAY['UNPAID', 'PAID', 'SHIPPED', 'DELIVERED'], EXCLUDED.status)
                 > array_position(ARRAY['UNPAID', 'PAID', 'SHIPPED', 'DELIVERED'], orders.status)
            )
        )
    )
    AND (orders.buyer_name, orders.status, orders.total_amount, orders.currency,
         orders.price_tier, orders.created_at, orders.paid_at, orders.shipped_at,
         orders.raw_payload)
        IS DISTINCT FROM
        (EXCLUDED.buyer_name, EXCLUDED.status, EXCLUDED.total_amount, EXCLUDED.currency,
         EXCLUDED.price_tier, EXCLUDED.created_at, EXCLUDED.paid_at, EXCLUDED.shipped_at,
         EXCLUDED.raw_payload)
RETURNING (xmax = 0) AS inserted
"""


@dataclass
class WriteResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def write_orders(conn, orders: list[CanonicalOrder]) -> WriteResult:
    """Upsert the whole batch in one transaction, then commit once.

    If any row fails, the transaction is rolled back and the error re-raised,
    so the caller never advances the watermark past a half-written batch.
    """
    result = WriteResult()
    if not orders:
        return result
    try:
        for order in orders:
            if order.status not in FORWARD_STATUSES + TERMINAL_STATUSES:
                raise ValueError(f"unknown status {order.status!r} for {order.source_order_id}")
            row = conn.execute(UPSERT_SQL, (
                order.source, order.source_order_id, order.buyer_name, order.status,
                order.total_amount, order.currency, order.price_tier, order.created_at,
                order.paid_at, order.shipped_at, json.dumps(order.raw_payload),
            )).fetchone()
            if row is None:
                result.skipped += 1
            elif row[0]:
                result.inserted += 1
            else:
                result.updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return result

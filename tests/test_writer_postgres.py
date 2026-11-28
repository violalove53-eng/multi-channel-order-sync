"""Tests for write_orders against a real Postgres.

The upsert's insert / update / skip decision lives in SQL, so it's tested
against a real database, not a fake. Each test gets a fresh schema built from
db/schema.sql and dropped afterwards.

Skipped unless psycopg is installed and ORDER_SYNC_TEST_DSN points at a
database you're happy to create throwaway schemas in, e.g.:
    ORDER_SYNC_TEST_DSN=postgresql://localhost/order_sync_test python3 -m unittest -v
"""

import os
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.models import CanonicalOrder
from core.writer import write_orders

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

DSN = os.environ.get("ORDER_SYNC_TEST_DSN")
SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text()
T0 = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)


def order(n, status="PAID", amount=1999, **extra):
    return CanonicalOrder(
        source="shopify",
        source_order_id=f"gid://shopify/Order/{n}",
        status=status,
        total_amount=amount,
        currency="USD",
        created_at=T0,
        raw_payload={"id": f"gid://shopify/Order/{n}", "status": status, "amount": amount},
        **extra,
    )


@unittest.skipUnless(psycopg and DSN, "set ORDER_SYNC_TEST_DSN (and install psycopg) to run")
class WriteOrdersPostgresTests(unittest.TestCase):

    def setUp(self):
        self.schema = f"test_{uuid.uuid4().hex[:12]}"
        self.conn = psycopg.connect(DSN)
        self.conn.execute(f"CREATE SCHEMA {self.schema}")
        self.conn.execute(f"SET search_path TO {self.schema}")
        self.conn.execute(SCHEMA_SQL)
        self.conn.commit()

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute(f"DROP SCHEMA {self.schema} CASCADE")
        self.conn.commit()
        self.conn.close()

    def rows(self):
        return self.conn.execute(
            "SELECT source, source_order_id, status, total_amount, raw_payload"
            " FROM orders ORDER BY source_order_id"
        ).fetchall()

    def status_of(self, n):
        return self.conn.execute(
            "SELECT status FROM orders WHERE source_order_id = %s",
            (f"gid://shopify/Order/{n}",),
        ).fetchone()[0]

    # --- insert / skip / update -------------------------------------------

    def test_first_write_inserts_everything(self):
        result = write_orders(self.conn, [order(1), order(2)])
        self.assertEqual((result.inserted, result.updated, result.skipped), (2, 0, 0))
        self.assertEqual(len(self.rows()), 2)

    def test_same_batch_three_times_is_identical(self):
        # Acceptance criterion from docs/design.md
        batch = [order(1), order(2, status="SHIPPED"), order(3, status="UNPAID")]
        write_orders(self.conn, batch)
        after_first = self.rows()
        for _ in range(2):
            result = write_orders(self.conn, batch)
            self.assertEqual((result.inserted, result.updated, result.skipped), (0, 0, 3))
        self.assertEqual(self.rows(), after_first)

    def test_unchanged_rerun_leaves_last_seen_at_alone(self):
        write_orders(self.conn, [order(1)])
        before = self.conn.execute("SELECT last_seen_at FROM orders").fetchone()[0]
        write_orders(self.conn, [order(1)])
        after = self.conn.execute("SELECT last_seen_at FROM orders").fetchone()[0]
        self.assertEqual(before, after)

    def test_same_status_with_other_changes_updates(self):
        write_orders(self.conn, [order(1, amount=1999)])
        result = write_orders(self.conn, [order(1, amount=2499)])
        self.assertEqual((result.inserted, result.updated, result.skipped), (0, 1, 0))
        self.assertEqual(self.rows()[0][3], 2499)

    def test_forward_status_updates(self):
        write_orders(self.conn, [order(1, status="PAID")])
        result = write_orders(self.conn, [order(1, status="SHIPPED")])
        self.assertEqual(result.updated, 1)
        self.assertEqual(self.status_of(1), "SHIPPED")

    def test_mixed_batch_counts(self):
        write_orders(self.conn, [order(1), order(2, status="UNPAID")])
        result = write_orders(self.conn, [
            order(1),                      # unchanged -> skip
            order(2, status="PAID"),       # forward  -> update
            order(3),                      # new      -> insert
        ])
        self.assertEqual((result.inserted, result.updated, result.skipped), (1, 1, 1))

    # --- status never moves backwards -------------------------------------

    def test_stale_record_cannot_move_status_backwards(self):
        write_orders(self.conn, [order(1, status="SHIPPED", amount=1999)])
        result = write_orders(self.conn, [order(1, status="PAID", amount=5)])
        self.assertEqual((result.inserted, result.updated, result.skipped), (0, 0, 1))
        self.assertEqual(self.status_of(1), "SHIPPED")
        self.assertEqual(self.rows()[0][3], 1999)  # the stale record's other fields are ignored too

    def test_cancel_and_refund_are_reachable_from_any_status(self):
        write_orders(self.conn, [order(1, status="SHIPPED"), order(2, status="UNPAID")])
        write_orders(self.conn, [order(1, status="REFUNDED"), order(2, status="CANCELLED")])
        self.assertEqual(self.status_of(1), "REFUNDED")
        self.assertEqual(self.status_of(2), "CANCELLED")

    def test_terminal_status_never_changes(self):
        write_orders(self.conn, [order(1, status="CANCELLED"), order(2, status="REFUNDED")])
        result = write_orders(self.conn, [order(1, status="PAID"), order(2, status="CANCELLED")])
        self.assertEqual(result.skipped, 2)
        self.assertEqual(self.status_of(1), "CANCELLED")
        self.assertEqual(self.status_of(2), "REFUNDED")

    def test_terminal_order_can_still_refresh_its_other_fields(self):
        write_orders(self.conn, [order(1, status="REFUNDED", amount=1999)])
        result = write_orders(self.conn, [order(1, status="REFUNDED", amount=0)])
        self.assertEqual(result.updated, 1)
        self.assertEqual(self.rows()[0][3], 0)

    # --- one transaction per batch ----------------------------------------

    def test_failure_mid_batch_writes_nothing(self):
        write_orders(self.conn, [order(1, status="UNPAID")])
        with self.assertRaises(ValueError):
            write_orders(self.conn, [order(1, status="PAID"), order(2), order(3, status="LOST")])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.status_of(1), "UNPAID")

    def test_sources_do_not_collide(self):
        tiktok = CanonicalOrder(
            source="tiktok", source_order_id="gid://shopify/Order/1", status="PAID",
            total_amount=499, currency="USD", created_at=T0, raw_payload={},
        )
        result = write_orders(self.conn, [order(1), tiktok])
        self.assertEqual(result.inserted, 2)

    def test_empty_batch_is_a_no_op(self):
        result = write_orders(self.conn, [])
        self.assertEqual((result.inserted, result.updated, result.skipped), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()

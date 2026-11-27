"""Tests for load_watermark, save_watermark and sync_shopify.

No database and no network: FakeConn stands in for a psycopg 3 connection
and keeps the watermarks table in a dict; FakeShopify returns canned orders.

Run from the project root:
    python3 -m unittest -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from core.models import RawOrder
from sync_shopify import OVERLAP, load_watermark, save_watermark, sync_shopify

T0 = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Understands only the two SQL statements the watermark functions send."""

    def __init__(self, watermarks=None):
        self.watermarks = dict(watermarks or {})
        self.commits = 0
        self.writes = 0

    def execute(self, sql, params):
        sql = " ".join(sql.split())
        if sql.startswith("SELECT last_synced_at FROM watermarks"):
            (source,) = params
            value = self.watermarks.get(source)
            return FakeResult((value,) if value is not None else None)
        if sql.startswith("INSERT INTO watermarks"):
            source, last_synced_at = params
            self.watermarks[source] = last_synced_at
            self.writes += 1
            return FakeResult(None)
        raise AssertionError(f"unexpected SQL: {sql}")

    def commit(self):
        self.commits += 1


class FakeShopify:
    def __init__(self, orders):
        self.orders = orders
        self.calls = []

    def fetch_orders(self, since):
        self.calls.append(since)
        return list(self.orders)


def order(n, updated_at):
    return RawOrder("shopify", f"gid://shopify/Order/{n}", updated_at, {"name": f"#{n}"})


class LoadWatermarkTests(unittest.TestCase):

    def test_returns_none_when_no_row(self):
        self.assertIsNone(load_watermark(FakeConn(), "shopify"))

    def test_returns_stored_value(self):
        conn = FakeConn({"shopify": T0})
        self.assertEqual(load_watermark(conn, "shopify"), T0)

    def test_reads_only_its_own_source(self):
        conn = FakeConn({"tiktok": T0})
        self.assertIsNone(load_watermark(conn, "shopify"))


class SaveWatermarkTests(unittest.TestCase):

    def test_inserts_new_row_and_commits(self):
        conn = FakeConn()
        save_watermark(conn, "shopify", T0)
        self.assertEqual(conn.watermarks["shopify"], T0)
        self.assertEqual(conn.commits, 1)

    def test_overwrites_existing_row(self):
        conn = FakeConn({"shopify": T0})
        later = T0 + timedelta(hours=1)
        save_watermark(conn, "shopify", later)
        self.assertEqual(conn.watermarks["shopify"], later)


class SyncShopifyTests(unittest.TestCase):

    def test_first_run_does_full_sync_and_saves_max(self):
        conn = FakeConn()
        shopify = FakeShopify([order(1, T0), order(2, T0 + timedelta(minutes=5))])
        sync_shopify(conn, shopify)
        self.assertEqual(shopify.calls, [None])
        self.assertEqual(conn.watermarks["shopify"], T0 + timedelta(minutes=5))

    def test_rewinds_15_minutes_from_stored_watermark(self):
        conn = FakeConn({"shopify": T0})
        shopify = FakeShopify([])
        sync_shopify(conn, shopify)
        self.assertEqual(shopify.calls, [T0 - OVERLAP])

    def test_advances_to_latest_updated_at_regardless_of_order(self):
        conn = FakeConn({"shopify": T0})
        latest = T0 + timedelta(minutes=30)
        shopify = FakeShopify([
            order(1, T0 + timedelta(minutes=10)),
            order(2, latest),
            order(3, T0 + timedelta(minutes=20)),
        ])
        sync_shopify(conn, shopify)
        self.assertEqual(conn.watermarks["shopify"], latest)

    def test_overlap_orders_never_move_watermark_backwards(self):
        # Orders inside the 15-minute rewind are older than the stored watermark.
        conn = FakeConn({"shopify": T0})
        shopify = FakeShopify([order(1, T0 - timedelta(minutes=10))])
        sync_shopify(conn, shopify)
        self.assertEqual(conn.watermarks["shopify"], T0)
        self.assertEqual(conn.writes, 0)

    def test_first_run_with_no_orders_saves_nothing(self):
        conn = FakeConn()
        sync_shopify(conn, FakeShopify([]))
        self.assertNotIn("shopify", conn.watermarks)
        self.assertEqual(conn.writes, 0)

    def test_no_new_orders_skips_the_write(self):
        conn = FakeConn({"shopify": T0})
        sync_shopify(conn, FakeShopify([order(1, T0)]))
        self.assertEqual(conn.writes, 0)

    def test_fetch_failure_leaves_watermark_untouched(self):
        class Boom(FakeShopify):
            def fetch_orders(self, since):
                raise RuntimeError("Shopify down")

        conn = FakeConn({"shopify": T0})
        with self.assertRaises(RuntimeError):
            sync_shopify(conn, Boom([]))
        self.assertEqual(conn.watermarks["shopify"], T0)
        self.assertEqual(conn.writes, 0)


if __name__ == "__main__":
    unittest.main()

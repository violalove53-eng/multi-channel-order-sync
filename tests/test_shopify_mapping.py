"""Tests for the Shopify -> canonical order mapping. Pure functions, no I/O.

Run from the project root:
    python3 -m unittest -v
"""

import unittest
from datetime import datetime, timezone

from connectors.shopify_mapping import map_shopify_order, map_status, to_cents
from core.models import RawOrder


def node(**overrides):
    base = {
        "id": "gid://shopify/Order/1001",
        "name": "#1001",
        "createdAt": "2026-11-20T14:03:22Z",
        "updatedAt": "2026-11-21T09:00:00Z",
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "totalPriceSet": {"shopMoney": {"amount": "24.98", "currencyCode": "USD"}},
    }
    base.update(overrides)
    return base


def raw(n):
    return RawOrder("shopify", n["id"],
                    datetime.fromisoformat(n["updatedAt"].replace("Z", "+00:00")), n)


class MapStatusTests(unittest.TestCase):

    def test_unpaid_and_unfulfilled(self):
        self.assertEqual(map_status("PENDING", "UNFULFILLED"), "UNPAID")

    def test_authorized_is_not_paid_yet(self):
        self.assertEqual(map_status("AUTHORIZED", "UNFULFILLED"), "UNPAID")

    def test_paid(self):
        self.assertEqual(map_status("PAID", "UNFULFILLED"), "PAID")

    def test_partially_refunded_still_counts_as_paid(self):
        self.assertEqual(map_status("PARTIALLY_REFUNDED", "UNFULFILLED"), "PAID")

    def test_partially_fulfilled_is_not_shipped(self):
        self.assertEqual(map_status("PAID", "PARTIALLY_FULFILLED"), "PAID")

    def test_fulfilled_is_shipped(self):
        self.assertEqual(map_status("PAID", "FULFILLED"), "SHIPPED")

    def test_refunded_wins_over_fulfilled(self):
        self.assertEqual(map_status("REFUNDED", "FULFILLED"), "REFUNDED")

    def test_voided_and_expired_are_cancelled(self):
        self.assertEqual(map_status("VOIDED", "UNFULFILLED"), "CANCELLED")
        self.assertEqual(map_status("EXPIRED", "UNFULFILLED"), "CANCELLED")

    def test_missing_fields_default_to_unpaid(self):
        self.assertEqual(map_status(None, None), "UNPAID")


class ToCentsTests(unittest.TestCase):

    def test_two_decimals(self):
        self.assertEqual(to_cents("24.98"), 2498)

    def test_whole_number(self):
        self.assertEqual(to_cents("5"), 500)
        self.assertEqual(to_cents("5.0"), 500)

    def test_no_float_drift(self):
        # float("0.29") * 100 == 28.999999999999996
        self.assertEqual(to_cents("0.29"), 29)

    def test_rejects_fractions_of_a_cent(self):
        with self.assertRaises(ValueError):
            to_cents("1.005")


class MapShopifyOrderTests(unittest.TestCase):

    def test_maps_every_column(self):
        n = node()
        order = map_shopify_order(raw(n))
        self.assertEqual(order.source, "shopify")
        self.assertEqual(order.source_order_id, "gid://shopify/Order/1001")
        self.assertEqual(order.status, "PAID")
        self.assertEqual(order.total_amount, 2498)
        self.assertEqual(order.currency, "USD")
        self.assertEqual(order.created_at, datetime(2026, 11, 20, 14, 3, 22, tzinfo=timezone.utc))
        self.assertIs(order.raw_payload, n)
        # Not fetched by the current query
        self.assertIsNone(order.buyer_name)
        self.assertIsNone(order.paid_at)
        self.assertIsNone(order.shipped_at)
        self.assertIsNone(order.price_tier)

    def test_currency_comes_from_shop_money(self):
        n = node(totalPriceSet={"shopMoney": {"amount": "10.00", "currencyCode": "CAD"}})
        self.assertEqual(map_shopify_order(raw(n)).currency, "CAD")


if __name__ == "__main__":
    unittest.main()

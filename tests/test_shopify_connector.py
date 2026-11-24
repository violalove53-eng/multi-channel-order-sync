"""Tests for ShopifyConnector.fetch_orders.

No network: urlopen is replaced with fake responses, so these tests never
contact Shopify and never read .env.

Run from the project root:
    python3 -m unittest -v
"""

import io
import json
import unittest
import urllib.parse
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from connectors.shopify_connector import ShopifyConnector
from core.models import RawOrder

URLOPEN = "connectors.shopify_connector.urllib.request.urlopen"


def fake_response(body: dict) -> io.BytesIO:
    """What urlopen returns: something that works in `with` and has .read()."""
    return io.BytesIO(json.dumps(body).encode())


def token_response() -> io.BytesIO:
    return fake_response({"access_token": "test-token", "scope": "read_orders"})


def orders_response(*nodes: dict, has_next_page: bool = False) -> io.BytesIO:
    """The shape Shopify's GraphQL API returns: data -> orders -> edges -> node."""
    return fake_response({
        "data": {
            "orders": {
                "edges": [{"node": node} for node in nodes],
                "pageInfo": {"hasNextPage": has_next_page},
            }
        }
    })


def order_node(number: int, updated_at: str = "2026-11-20T14:03:22Z") -> dict:
    return {
        "id": f"gid://shopify/Order/{5000 + number}",
        "name": f"#{1000 + number}",
        "updatedAt": updated_at,
        "displayFinancialStatus": "PAID",
    }


class FetchOrdersTest(unittest.TestCase):

    def setUp(self):
        self.connector = ShopifyConnector("test-store.myshopify.com", "id", "secret")

    def fetch(self, *responses, since=None):
        """Call fetch_orders with fake responses; return (orders, requests sent)."""
        # side_effect hands out one response per urlopen call, in order.
        # An unexpected extra call raises StopIteration and fails the test.
        with patch(URLOPEN, side_effect=list(responses)) as urlopen:
            with redirect_stdout(io.StringIO()):  # hide the "granted scopes" print
                orders = self.connector.fetch_orders(since)
        requests = [call.args[0] for call in urlopen.call_args_list]
        return orders, requests

    # --- The loop: each edge["node"] becomes one RawOrder ---

    def test_each_node_becomes_one_raw_order(self):
        orders, _ = self.fetch(token_response(),
                               orders_response(order_node(1), order_node(2)))

        self.assertEqual(len(orders), 2)
        self.assertIsInstance(orders[0], RawOrder)
        self.assertEqual(orders[0].source, "shopify")

    def test_empty_page_returns_empty_list(self):
        orders, _ = self.fetch(token_response(), orders_response())

        self.assertEqual(orders, [])

if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from core.connector import OrderConnector
from core.models import RawOrder

API_VERSION = "2026-10"

ORDERS_QUERY = """
query ShopifyOrders($first: Int!, $queryStr: String) {
  orders(first: $first, query: $queryStr, sortKey: UPDATED_AT) {
    edges {
      node {
	id
	name
	createdAt
	updatedAt
	displayFinancialStatus
	displayFulfillmentStatus
   	currencyCode
	totalPriceSet {  shopMoney {  amount currencyCode  }  }
	lineItems(first: 20) {
	  nodes {
	    title
	    quantity
	    sku
	    originalUnitPriceSet {  shopMoney {  amount currencyCode  } }
	}
      }
    }
  }
 } 
}
"""

def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

class ShopifyConnector(OrderConnector):

    def __init__(self, store_domain: str, client_id: str, client_secret:str) -> None:
        self.store_domain = store_domain
        self.client_id = client_id
        self.client_secret = client_secret

    @classmethod
    def from_env(cls) -> "ShopifyConnector":
        _load_dotenv()
        missing = [k for k in ("SHOPIFY_STORE_DOMAIN", "SHOPIFY_CLIENT_ID",
                               "SHOPIFY_CLIENT_SECRET")
                   if not os.environ.get(k)]
        if missing:
            raise ValueError("missing in .env: " + ", ".join(missing))
        return cls(os.environ["SHOPIFY_STORE_DOMAIN"],
                   os.environ["SHOPIFY_CLIENT_ID"],
                   os.environ["SHOPIFY_CLIENT_SECRET"])

    def _request_token(self) -> str:
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }).encode()
        req = urllib.request.Request(
            f"https://{self.store_domain}/admin/oauth/access_token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        print("granted scopes:", data.get("scope"))  # For tonight's acceptance check: must include read_orders; delete this line once it works
        return data["access_token"]

    def fetch_orders(self, since: datetime | None) -> list[RawOrder]:
        token = self._request_token()
        query_str = None
        if since is not None:
            stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            query_str = f"updated_at:>='{stamp}'"
        payload = json.dumps({"query": ORDERS_QUERY,
                              "variables": {"first": 50, "queryStr": query_str}}).encode()
        req = urllib.request.Request(
            f"https://{self.store_domain}/admin/api/{API_VERSION}/graphql.json",
            data=payload,
            headers={"Content-Type": "application/json",
                     "X-Shopify-Access-Token": token},
            method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        if "errors" in data:
            raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")
        orders = []
        for edge in data["data"]["orders"]["edges"]:  # First page only for tonight; 4 orders is enough. Pagination comes tomorrow night
            node = edge["node"]
            orders.append(RawOrder(
                source="shopify",
                source_order_id=node["id"],  # Use the gid as the unique key, not a display name like #1004
                source_updated_at=datetime.fromisoformat(node["updatedAt"].replace("Z", "+00:00")),
                payload=node))
        return orders 


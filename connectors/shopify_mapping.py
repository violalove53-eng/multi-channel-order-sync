"""Schema mapping: Shopify GraphQL order node -> CanonicalOrder.

The orders query in shopify_connector.py doesn't fetch the customer, paidAt or
fulfillment timestamps yet, so buyer_name, paid_at and shipped_at stay None.
The full node is still kept in raw_payload, so they can be backfilled later.
"""

from datetime import datetime
from decimal import Decimal

from core.models import CanonicalOrder, RawOrder

# displayFinancialStatus values that mean the order is over
_CANCELLED_FINANCIAL = {"VOIDED", "EXPIRED"}
# displayFinancialStatus values that mean the money has arrived
_PAID_FINANCIAL = {"PAID", "PARTIALLY_REFUNDED"}


def map_status(financial: str | None, fulfillment: str | None) -> str:
    """Collapse Shopify's two status fields into the canonical status enum.

    Shopify's order node doesn't report delivery, so DELIVERED never comes from here.
    """
    if financial == "REFUNDED":
        return "REFUNDED"
    if financial in _CANCELLED_FINANCIAL:
        return "CANCELLED"
    if fulfillment == "FULFILLED":
        return "SHIPPED"
    if financial in _PAID_FINANCIAL:
        return "PAID"
    return "UNPAID"


def to_cents(amount: str) -> int:
    """'12.34' -> 1234. Decimal, never float, so no rounding drift."""
    cents = Decimal(amount) * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"amount has more than 2 decimal places: {amount!r}")
    return int(cents)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def map_shopify_order(raw: RawOrder) -> CanonicalOrder:
    node = raw.payload
    money = node["totalPriceSet"]["shopMoney"]
    return CanonicalOrder(
        source=raw.source,
        source_order_id=raw.source_order_id,
        status=map_status(node.get("displayFinancialStatus"),
                          node.get("displayFulfillmentStatus")),
        total_amount=to_cents(money["amount"]),
        currency=money["currencyCode"],
        created_at=_parse_time(node["createdAt"]),
        raw_payload=node,
    )

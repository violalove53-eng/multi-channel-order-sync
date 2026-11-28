from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass
class RawOrder:
    source: str
    source_order_id: str
    source_updated_at: datetime
    payload: dict[str, Any]


@dataclass
class CanonicalOrder:
    """One row of the orders table: the unified model every source maps into."""
    source: str
    source_order_id: str
    status: str                      # UNPAID | PAID | SHIPPED | DELIVERED | CANCELLED | REFUNDED
    total_amount: int                # minor units (cents)
    currency: str
    created_at: datetime
    raw_payload: dict[str, Any]
    buyer_name: str | None = None
    price_tier: Decimal | None = None
    paid_at: datetime | None = None
    shipped_at: datetime | None = None

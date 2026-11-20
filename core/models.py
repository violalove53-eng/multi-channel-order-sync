from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class RawOrder:
    source: str
    source_order_id: str
    source_updated_at: datetime
    payload: dict[str, Any]

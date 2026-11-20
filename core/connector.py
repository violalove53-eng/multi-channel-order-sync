from abc import ABC, abstractmethod
from datetime import datetime

from core.models import RawOrder


class OrderConnector(ABC):

    @abstractmethod
    def fetch_orders(self, since: datetime | None) -> list[RawOrder]:
        ...

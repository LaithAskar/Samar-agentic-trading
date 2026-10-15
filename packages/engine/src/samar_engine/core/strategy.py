from __future__ import annotations

from abc import ABC, abstractmethod

from samar_engine.core.events import Bar
from samar_engine.core.orders import Order
from samar_engine.core.portfolio import Portfolio


class Strategy(ABC):
    name: str = "unnamed"

    def on_start(self, symbols: list[str]) -> None:
        return None

    @abstractmethod
    def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
        """See the closed bar and return orders.

        Those orders fill at the next bar's open. This bar is never a future bar.
        """

    def on_finish(self, portfolio: Portfolio) -> None:
        return None

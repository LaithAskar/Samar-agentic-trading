from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from samar_engine.core.orders import Fill, Order, Side


def _positions() -> dict[str, float]:
    return defaultdict(float)


def _prices() -> dict[str, float]:
    return {}


def _fills() -> list[Fill]:
    return []


def _curve() -> list[tuple[datetime, float]]:
    return []


@dataclass
class Portfolio:
    starting_cash: float
    cash: float = field(init=False)
    positions: dict[str, float] = field(default_factory=_positions)
    last_prices: dict[str, float] = field(default_factory=_prices)
    fills: list[Fill] = field(default_factory=_fills)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=_curve)

    def __post_init__(self) -> None:
        self.cash = self.starting_cash

    def apply_fill(self, fill: Fill) -> None:
        self.positions[fill.symbol] += fill.signed_quantity
        self.cash += fill.cash_delta
        if abs(self.positions[fill.symbol]) < 1e-9:
            del self.positions[fill.symbol]
        self.fills.append(fill)

    def fill_at(self, order: Order, price: float, timestamp: datetime) -> Fill:
        if order.side is Side.SELL:
            held = self.positions.get(order.symbol, 0.0)
            if order.quantity > held + 1e-9:
                raise ValueError(f"Cannot sell {order.quantity} {order.symbol}; only {held} held")
        else:
            cost = order.quantity * price
            if cost > self.cash + 1e-9:
                raise ValueError(
                    f"Insufficient cash for {order.quantity} {order.symbol} @ {price}: need {cost}, have {self.cash}"
                )

        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            timestamp=timestamp,
        )
        self.apply_fill(fill)
        return fill

    def mark(self, symbol: str, price: float) -> None:
        self.last_prices[symbol] = price

    def equity(self) -> float:
        positions_value = sum(qty * self.last_prices.get(sym, 0.0) for sym, qty in self.positions.items())
        return self.cash + positions_value

    def record_equity(self, timestamp: datetime) -> None:
        self.equity_curve.append((timestamp, self.equity()))

    def position(self, symbol: str) -> float:
        return self.positions.get(symbol, 0.0)

    def max_affordable(self, price: float, buffer_pct: float = 0.01) -> int:
        """Whole shares buyable after reserving buffer_pct of cash.

        Strategies size off the signal bar's close. Fills happen at the next
        open plus slippage, which can gap above that close. Spending every
        dollar makes the engine drop the order.
        """
        if not 0.0 <= buffer_pct < 1.0:
            raise ValueError("buffer_pct must be in [0, 1)")
        if price <= 0:
            return 0
        investable = self.cash * (1.0 - buffer_pct)
        return int(investable // price)

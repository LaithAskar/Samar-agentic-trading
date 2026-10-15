from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from samar_engine.core.events import Bar
from samar_engine.core.orders import Order, Side
from samar_engine.core.portfolio import Portfolio
from samar_engine.core.strategy import Strategy

DEFAULT_SLIPPAGE_BPS = 5.0


@dataclass
class BacktestResult:
    portfolio: Portfolio
    strategy_name: str
    symbol: str


class BacktestEngine:
    """One symbol. One fill model.

    Per bar:
      1. Fill orders from the previous bar at this bar's open, plus slippage.
      2. Mark to this bar's close.
      3. Record equity.
      4. Call on_bar with the closed bar.
      5. Hold the new orders for the next open.

    Orders still pending after the last bar are dropped.
    Buys fill at open * (1 + bps/10000). Sells fill at open * (1 - bps/10000).
    Commission is a flat dollar fee taken from cash after a successful fill.
    """

    def __init__(
        self,
        starting_cash: float = 100_000.0,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
        commission_per_trade: float = 0.0,
    ) -> None:
        if slippage_bps < 0 or commission_per_trade < 0:
            raise ValueError("slippage_bps and commission_per_trade must be >= 0")
        self.starting_cash = starting_cash
        self.slippage_bps = slippage_bps
        self.commission_per_trade = commission_per_trade

    def adjusted_fill_price(self, order: Order, raw_price: float) -> float:
        if self.slippage_bps == 0:
            return raw_price
        bps = self.slippage_bps / 10_000.0
        if order.side is Side.BUY:
            return round(raw_price * (1.0 + bps), 6)
        return round(raw_price * (1.0 - bps), 6)

    def run(self, strategy: Strategy, symbol: str, bars: Iterable[Bar]) -> BacktestResult:
        portfolio = Portfolio(starting_cash=self.starting_cash)
        strategy.on_start([symbol])
        pending: list[Order] = []

        for bar in bars:
            for order in pending:
                fill_price = self.adjusted_fill_price(order, bar.open)
                try:
                    portfolio.fill_at(order, price=fill_price, timestamp=bar.timestamp)
                except ValueError:
                    continue
                if self.commission_per_trade > 0:
                    portfolio.cash -= self.commission_per_trade
            pending = []

            portfolio.mark(bar.symbol, bar.close)
            portfolio.record_equity(bar.timestamp)

            new_orders = strategy.on_bar(bar, portfolio)
            if new_orders:
                pending.extend(new_orders)

        strategy.on_finish(portfolio)
        return BacktestResult(portfolio=portfolio, strategy_name=strategy.name, symbol=symbol)

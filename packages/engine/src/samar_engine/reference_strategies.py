from __future__ import annotations

from collections import deque

from samar_engine.core.events import Bar
from samar_engine.core.orders import Order, Side
from samar_engine.core.portfolio import Portfolio
from samar_engine.core.strategy import Strategy


class SmaCross(Strategy):
    name = "sma_cross"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self.fast = fast
        self.slow = slow
        self._closes: deque[float] = deque(maxlen=slow)
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def _sma(self, n: int) -> float | None:
        if len(self._closes) < n:
            return None
        window = list(self._closes)[-n:]
        return sum(window) / n

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
        self._closes.append(bar.close)
        fast = self._sma(self.fast)
        slow = self._sma(self.slow)
        orders: list[Order] = []
        if fast is not None and slow is not None and self._prev_fast is not None and self._prev_slow is not None:
            crossed_up = self._prev_fast <= self._prev_slow and fast > slow
            crossed_down = self._prev_fast >= self._prev_slow and fast < slow
            held = portfolio.position(bar.symbol)
            if crossed_up and held == 0:
                qty = portfolio.max_affordable(bar.close)
                if qty > 0:
                    orders.append(Order(symbol=bar.symbol, side=Side.BUY, quantity=qty))
            elif crossed_down and held > 0:
                orders.append(Order(symbol=bar.symbol, side=Side.SELL, quantity=held))
        self._prev_fast = fast
        self._prev_slow = slow
        return orders


class RsiMeanReversion(Strategy):
    name = "rsi_mean_rev"

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ) -> None:
        if period < 2:
            raise ValueError("period must be >= 2")
        if not (0 < oversold < overbought < 100):
            raise ValueError("require 0 < oversold < overbought < 100")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._closes: deque[float] = deque(maxlen=period + 1)
        self._prev_rsi: float | None = None

    def _rsi(self) -> float | None:
        if len(self._closes) < self.period + 1:
            return None
        prices = list(self._closes)
        gains = 0.0
        losses = 0.0
        for index in range(1, len(prices)):
            change = prices[index] - prices[index - 1]
            if change > 0:
                gains += change
            else:
                losses += -change
        if losses == 0:
            return 100.0
        rs = (gains / self.period) / (losses / self.period)
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
        self._closes.append(bar.close)
        rsi = self._rsi()
        orders: list[Order] = []
        if rsi is not None and self._prev_rsi is not None:
            held = portfolio.position(bar.symbol)
            crossed_into_oversold = self._prev_rsi >= self.oversold and rsi < self.oversold
            crossed_into_overbought = self._prev_rsi <= self.overbought and rsi > self.overbought
            if crossed_into_oversold and held == 0:
                qty = portfolio.max_affordable(bar.close)
                if qty > 0:
                    orders.append(Order(symbol=bar.symbol, side=Side.BUY, quantity=qty))
            elif crossed_into_overbought and held > 0:
                orders.append(Order(symbol=bar.symbol, side=Side.SELL, quantity=held))
        self._prev_rsi = rsi
        return orders

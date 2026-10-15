from __future__ import annotations

from collections import deque


class Sma:
    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._values: deque[float] = deque(maxlen=period)

    def update(self, value: float) -> float | None:
        self._values.append(value)
        if len(self._values) < self.period:
            return None
        return sum(self._values) / self.period


class Ema:
    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._k = 2.0 / (period + 1)
        self._seed: list[float] = []
        self._value: float | None = None

    def update(self, value: float) -> float | None:
        if self._value is None:
            self._seed.append(value)
            if len(self._seed) < self.period:
                return None
            self._value = sum(self._seed) / self.period
            return self._value
        self._value = (value * self._k) + (self._value * (1.0 - self._k))
        return self._value


class Rsi:
    """Simple RSI. Average gain and loss over `period` changes, not Wilder smoothing.

    This matches the ported rsi_mean_rev strategy so the DSL and the class trade alike.
    """

    def __init__(self, period: int) -> None:
        if period < 2:
            raise ValueError("period must be >= 2")
        self.period = period
        self._closes: deque[float] = deque(maxlen=period + 1)

    def update(self, close: float) -> float | None:
        self._closes.append(close)
        if len(self._closes) < self.period + 1:
            return None
        prices = list(self._closes)
        gains = 0.0
        losses = 0.0
        for prev, cur in zip(prices, prices[1:], strict=False):
            change = cur - prev
            if change > 0:
                gains += change
            else:
                losses += -change
        if losses == 0:
            return 100.0
        rs = (gains / self.period) / (losses / self.period)
        return 100.0 - (100.0 / (1.0 + rs))


class Price:
    def __init__(self) -> None:
        self._value: float | None = None

    def update(self, close: float) -> float:
        self._value = close
        return close

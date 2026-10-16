from __future__ import annotations

import csv
import os
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from samar_engine.core.events import Bar

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def bars_from_csv(path: Path, symbol: str) -> list[Bar]:
    bars: list[Bar] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=datetime.fromisoformat(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return bars


ARENA_TICKERS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "SPY",
    "QQQ",
)
REAL_DATA = "REAL DATA"
SYNTHETIC_DATA = "SYNTHETIC DATA"
FULL_START = date(1990, 1, 1)
FULL_END = date(2100, 1, 1)


class MarketData(Protocol):
    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        """Daily bars with timestamps in [start, end]."""
        ...

    def data_label(self, tickers: tuple[str, ...]) -> str:
        """REAL DATA when every ticker is a local cache file, otherwise SYNTHETIC DATA."""
        ...


class MemoryMarketData:
    def __init__(self, series: dict[str, list[Bar]]) -> None:
        self._series = series

    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        rows = self._series.get(ticker.upper(), [])
        return [bar for bar in rows if start <= bar.timestamp.date() <= end]

    def data_label(self, tickers: tuple[str, ...]) -> str:
        del tickers
        return SYNTHETIC_DATA


class FixtureMarketData:
    """Seeded daily bars from scripts/write_price_fixtures.py. Tests never touch the network."""

    def __init__(self, root: Path = FIXTURE_DIR) -> None:
        self._root = root
        self._cache: dict[str, list[Bar]] = {}

    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        symbol = ticker.upper()
        if symbol not in self._cache:
            path = self._root / f"{symbol}.csv"
            if not path.exists():
                raise KeyError(f"no fixture for {symbol}")
            self._cache[symbol] = bars_from_csv(path, symbol)
        return [bar for bar in self._cache[symbol] if start <= bar.timestamp.date() <= end]

    def data_label(self, tickers: tuple[str, ...]) -> str:
        del tickers
        return SYNTHETIC_DATA


class PreferLocalMarketData:
    """Read data/market when that CSV exists. Otherwise use the committed synthetic fixture."""

    def __init__(self, cache_dir: Path | None = None, fixtures: FixtureMarketData | None = None) -> None:
        self._cache = cache_dir or Path(os.environ.get("SAMAR_MARKET_DIR", "data/market"))
        self._fixtures = fixtures or FixtureMarketData()

    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        symbol = ticker.upper()
        path = self._cache / f"{symbol}.csv"
        if path.is_file():
            series = bars_from_csv(path, symbol)
            return [bar for bar in series if start <= bar.timestamp.date() <= end]
        return self._fixtures.bars(symbol, start, end)

    def data_label(self, tickers: tuple[str, ...]) -> str:
        if tickers and all((self._cache / f"{ticker.upper()}.csv").is_file() for ticker in tickers):
            return REAL_DATA
        return SYNTHETIC_DATA

from __future__ import annotations

import csv
import json
import urllib.request
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


class MarketData(Protocol):
    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        """Daily bars with timestamps in [start, end]."""
        ...


class MemoryMarketData:
    def __init__(self, series: dict[str, list[Bar]]) -> None:
        self._series = series

    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        rows = self._series.get(ticker.upper(), [])
        return [bar for bar in rows if start <= bar.timestamp.date() <= end]


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


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    parsed: dict[str, object] = {}
    for key in value:
        if isinstance(key, str):
            parsed[key] = value[key]
    return parsed


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("expected a JSON list")
    return [item for item in value if item is None or isinstance(item, (str, int, float, dict, list))]


def _objects(values: list[object]) -> list[dict[str, object]]:
    return [_object(item) for item in values if isinstance(item, dict)]


def _as_floats(values: object) -> list[float | None]:
    if not isinstance(values, list):
        raise ValueError("quote series is not a list")
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
        else:
            out.append(float(value))
    return out


class YFinanceMarketData:
    """Yahoo chart endpoint, the same feed yfinance reads. Not used in unit tests."""

    def bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        period1 = int(datetime(start.year, start.month, start.day).timestamp())
        period2 = int(datetime(end.year, end.month, end.day).timestamp()) + 86400
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{ticker}?period1={period1}&period2={period2}&interval=1d"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "samar"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = _object(json.load(response))
        chart = _object(payload["chart"])
        results = _objects(_as_list(chart["result"]))
        if not results:
            raise ValueError("yahoo chart has no result")
        result = results[0]
        stamps = _as_list(result["timestamp"])
        indicators = _object(result["indicators"])
        quotes = _objects(_as_list(indicators["quote"]))
        if not quotes:
            raise ValueError("yahoo quote missing")
        quote = quotes[0]
        opens = _as_floats(quote["open"])
        highs = _as_floats(quote["high"])
        lows = _as_floats(quote["low"])
        closes = _as_floats(quote["close"])
        volumes = _as_floats(quote["volume"])
        bars: list[Bar] = []
        for index, stamp in enumerate(stamps):
            raw_open = opens[index]
            raw_close = closes[index]
            raw_high = highs[index]
            raw_low = lows[index]
            if None in (raw_open, raw_close, raw_high, raw_low):
                continue
            if raw_open is None or raw_close is None or raw_high is None or raw_low is None:
                continue
            volume = volumes[index]
            if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
                continue
            bars.append(
                Bar(
                    symbol=ticker.upper(),
                    timestamp=datetime.fromtimestamp(float(stamp)),
                    open=raw_open,
                    high=raw_high,
                    low=raw_low,
                    close=raw_close,
                    volume=0.0 if volume is None else volume,
                )
            )
        return bars

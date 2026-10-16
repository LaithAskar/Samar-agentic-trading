"""Write the frozen daily bars the backtests read.

The series is a seeded random walk owned by this repository. It is not a
download. Yahoo Finance tells readers not to redistribute information it
provides (https://help.yahoo.com/kb/SLN2310.html), so the earlier Yahoo chart
pull is not stored here.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packages" / "data" / "src" / "samar_data" / "fixtures"
START = date(2020, 1, 2)
END = date(2024, 12, 31)


def _rows(seed: int, start_price: float) -> list[tuple[str, float, float, float, float, int]]:
    rng = random.Random(seed)  # noqa: S311
    price = start_price
    day = START
    rows: list[tuple[str, float, float, float, float, int]] = []
    while day <= END:
        if day.weekday() < 5:
            close = max(1.0, price * (1.0 + rng.gauss(0.0004, 0.012)))
            open_ = price
            high = max(open_, close) * (1.0 + rng.random() * 0.004)
            low = min(open_, close) * (1.0 - rng.random() * 0.004)
            volume = rng.randint(1_000_000, 20_000_000)
            rows.append((day.isoformat(), open_, high, low, close, volume))
            price = close
        day += timedelta(days=1)
    return rows


def write_symbol(symbol: str, seed: int, start_price: float) -> Path:
    path = OUT / f"{symbol}.csv"
    OUT.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        writer.writerows(_rows(seed, start_price))
    return path


def main() -> None:
    write_symbol("AAPL", 20201014, 100.0)
    write_symbol("SPY", 20201015, 300.0)


if __name__ == "__main__":
    main()

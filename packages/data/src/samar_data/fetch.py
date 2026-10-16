"""Download personal Public.com chart bars into data/market/.

Yahoo Finance forbids automated collection without prior permission, and it
forbids redistribution. Alpha Vantage's free key returns 100 daily points;
the full history is a paid plan. Stooq is personal-use only and has been
refusing scripted downloads. Public's individual API is the key this person
already uses. The market-data addendum allows a non-professional to receive
bars for their own personal, non-business use and forbids passing them on.
The files stay in the gitignored data/ directory.

Public's historic chart schema has open, high, low, close, and volume. It
does not publish a separate adjusted-close field. TEN_YEARS is the daily
regular-session series the chart uses for that window.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
from samar_engine.core.events import Bar

from samar_data.market import ARENA_TICKERS

AUTH_URL = "https://api.public.com/userapiauthservice/personal/access-tokens"
GATEWAY = "https://api.public.com/userapigateway"
PERIOD = "TEN_YEARS"


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    parsed: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(key, str):
            parsed[key] = item
    return parsed


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed


def _daily(symbol: str, rows: list[dict[str, object]]) -> list[Bar]:
    grouped: dict[date, list[tuple[datetime, float, float, float, float, float]]] = {}
    for row in rows:
        stamp = _stamp(row.get("timestamp"))
        open_ = _number(row.get("open"))
        high = _number(row.get("high"))
        low = _number(row.get("low"))
        close = _number(row.get("close"))
        volume = _number(row.get("volume"))
        if stamp is None or None in (open_, high, low, close):
            continue
        if open_ is None or high is None or low is None or close is None:
            continue
        grouped.setdefault(stamp.date(), []).append((stamp, open_, high, low, close, 0.0 if volume is None else volume))
    bars: list[Bar] = []
    for day in sorted(grouped):
        chunk = sorted(grouped[day], key=lambda item: item[0])
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=datetime(day.year, day.month, day.day),
                open=chunk[0][1],
                high=max(item[2] for item in chunk),
                low=min(item[3] for item in chunk),
                close=chunk[-1][4],
                volume=sum(item[5] for item in chunk),
            )
        )
    return bars


def bars_from_public(symbol: str, payload: object) -> list[Bar]:
    body = _object(payload)
    regular = body.get("regularMarket")
    raw_rows: object
    if isinstance(regular, dict):
        raw_rows = _object(regular).get("bars")
    else:
        raw_rows = body.get("bars")
    if not isinstance(raw_rows, list):
        raise ValueError(f"{symbol} history did not include regularMarket.bars")
    rows = [_object(item) for item in raw_rows if isinstance(item, dict)]
    bars = _daily(symbol.upper(), rows)
    if len(bars) < 2:
        raise ValueError(f"{symbol} returned fewer than 2 daily bars")
    return bars


def _token(client: httpx.Client, auth_url: str, secret: str) -> str:
    response = client.post(auth_url, json={"secret": secret, "validityInMinutes": 15})
    response.raise_for_status()
    token = _object(response.json()).get("accessToken")
    if not isinstance(token, str) or not token:
        raise ValueError("Public token response missing accessToken")
    return token


def _history(client: httpx.Client, gateway: str, token: str, symbol: str) -> list[Bar]:
    response = client.get(
        f"{gateway}/historicdata/EQUITY/{symbol}/{PERIOD}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return bars_from_public(symbol, response.json())


def write_bars(path: Path, bars: list[Bar]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow(
                [
                    bar.timestamp.date().isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    int(bar.volume),
                ]
            )


def fetch_to_cache(
    symbols: list[str],
    secret: str,
    cache: Path,
    client: httpx.Client,
    *,
    auth_url: str = AUTH_URL,
    gateway: str = GATEWAY,
) -> list[Path]:
    if not secret.strip():
        raise ValueError("Public secret is required")
    token = _token(client, auth_url, secret)
    paths: list[Path] = []
    for symbol in symbols:
        name = symbol.strip().upper()
        if not name:
            continue
        bars = _history(client, gateway, token, name)
        path = cache / f"{name}.csv"
        write_bars(path, bars)
        paths.append(path)
    if not paths:
        raise ValueError("name at least one ticker")
    return paths


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    symbols = [item.upper() for item in args] or list(ARENA_TICKERS)
    secret = os.environ.get("SAMAR_PUBLIC_SECRET", "")
    if not secret.strip():
        raise SystemExit(
            "Set SAMAR_PUBLIC_SECRET to your Public.com personal API secret. "
            "Bars are written to data/market/ and are not committed."
        )
    cache = Path(os.environ.get("SAMAR_MARKET_DIR", "data/market"))
    auth_url = os.environ.get("SAMAR_PUBLIC_AUTH_URL", AUTH_URL)
    gateway = os.environ.get("SAMAR_PUBLIC_GATEWAY", GATEWAY)
    with httpx.Client(timeout=60.0) as client:
        paths = fetch_to_cache(symbols, secret, cache, client, auth_url=auth_url, gateway=gateway)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()

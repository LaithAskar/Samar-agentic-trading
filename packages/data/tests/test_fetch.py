from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from samar_data.fetch import bars_from_public, fetch_to_cache
from samar_data.market import REAL_DATA, SYNTHETIC_DATA, FixtureMarketData, PreferLocalMarketData


def test_public_payload_rolls_up_to_one_daily_bar() -> None:
    payload = {
        "regularMarket": {
            "bars": [
                {
                    "timestamp": "2024-01-02T14:30:00Z",
                    "open": "10",
                    "high": "12",
                    "low": "9",
                    "close": "11",
                    "volume": 100,
                },
                {
                    "timestamp": "2024-01-02T20:00:00Z",
                    "open": "11",
                    "high": "13",
                    "low": "10",
                    "close": "12.5",
                    "volume": 50,
                },
                {
                    "timestamp": "2024-01-03T14:30:00Z",
                    "open": "12.5",
                    "high": "14",
                    "low": "12",
                    "close": "13",
                    "volume": 80,
                },
            ]
        }
    }
    bars = bars_from_public("aapl", payload)
    assert [(bar.timestamp.date().isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars] == [
        ("2024-01-02", 10.0, 13.0, 9.0, 12.5, 150.0),
        ("2024-01-03", 12.5, 14.0, 12.0, 13.0, 80.0),
    ]


def test_fetch_writes_a_gitignored_cache_from_mocked_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access-tokens"):
            body = json.loads(request.content)
            assert body["secret"] == "pub-demo-secret"
            return httpx.Response(200, json={"accessToken": "token-1"})
        assert request.headers["authorization"] == "Bearer token-1"
        assert request.url.path.endswith("/historicdata/EQUITY/SPY/TEN_YEARS")
        return httpx.Response(
            200,
            json={
                "regularMarket": {
                    "bars": [
                        {"timestamp": "2024-06-03", "open": "1", "high": "2", "low": "1", "close": "1.5", "volume": 3},
                        {
                            "timestamp": "2024-06-04",
                            "open": "1.5",
                            "high": "2",
                            "low": "1",
                            "close": "1.7",
                            "volume": 4,
                        },
                    ]
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    paths = fetch_to_cache(
        ["spy"],
        "pub-demo-secret",
        tmp_path,
        client,
        auth_url="https://broker.test/access-tokens",
        gateway="https://broker.test",
    )
    text = paths[0].read_text()
    assert paths[0].name == "SPY.csv"
    assert "2024-06-03,1.0,2.0,1.0,1.5,3" in text
    assert "2024-06-04,1.5,2.0,1.0,1.7,4" in text


def test_default_cache_directory_follows_samar_market_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMAR_MARKET_DIR", str(tmp_path))
    (tmp_path / "QQQ.csv").write_text(
        "date,open,high,low,close,volume\n2024-01-02,1,1,1,1,1\n",
        encoding="utf-8",
    )
    market = PreferLocalMarketData()
    assert market.data_label(("QQQ",)) == REAL_DATA
    assert market.bars("QQQ", date(2024, 1, 2), date(2024, 1, 2))[0].close == 1.0


def test_local_cache_is_preferred_and_missing_files_stay_synthetic(tmp_path: Path) -> None:
    cached = tmp_path / "AAPL.csv"
    cached.write_text(
        "date,open,high,low,close,volume\n2021-03-01,40,41,39,40.5,10\n2021-03-02,40.5,42,40,41,11\n",
        encoding="utf-8",
    )
    market = PreferLocalMarketData(tmp_path, FixtureMarketData())
    real = market.bars("AAPL", date(2021, 3, 1), date(2021, 3, 2))
    assert [bar.close for bar in real] == [40.5, 41.0]
    assert market.data_label(("AAPL",)) == REAL_DATA
    synthetic = market.bars("SPY", date(2020, 1, 2), date(2020, 1, 2))
    assert synthetic[0].close != 40.5
    assert market.data_label(("AAPL", "SPY")) == SYNTHETIC_DATA
    assert market.data_label(("SPY",)) == SYNTHETIC_DATA

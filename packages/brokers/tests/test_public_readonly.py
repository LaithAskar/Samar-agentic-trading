from __future__ import annotations

import ast
import inspect
from pathlib import Path

import httpx
from samar_brokers.limiter import TokenBucket
from samar_brokers.public_readonly import PublicReadOnly


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_sync_reads_accounts_and_portfolio_from_fixtures() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/access-tokens"):
            return httpx.Response(200, json={"accessToken": "short-lived"})
        if request.url.path.endswith("/trading/account"):
            return httpx.Response(200, json={"accounts": [{"accountId": "acc-1", "nickname": "Brokerage"}]})
        if request.url.path.endswith("/portfolio/v2"):
            return httpx.Response(
                200,
                json={
                    "equity": 1200.5,
                    "buyingPower": 40.0,
                    "positions": [
                        {
                            "instrument": {"symbol": "AAPL"},
                            "quantity": 2,
                            "currentValue": 500.0,
                        }
                    ],
                },
            )
        raise AssertionError(request.url.path)

    broker = PublicReadOnly("public-secret", _client(httpx.MockTransport(handler)))
    accounts = broker.list_accounts()
    portfolio = broker.get_portfolio("acc-1")
    assert accounts[0].account_id == "acc-1"
    assert accounts[0].nickname == "Brokerage"
    assert portfolio.equity == 1200.5
    assert portfolio.cash == 40.0
    assert portfolio.positions[0].symbol == "AAPL"
    assert portfolio.positions[0].quantity == 2.0
    assert calls == [
        "/userapiauthservice/personal/access-tokens",
        "/userapigateway/trading/account",
        "/userapigateway/trading/acc-1/portfolio/v2",
    ]


def test_public_readonly_has_no_order_methods() -> None:
    names = set(dir(PublicReadOnly))
    assert "place_order" not in names
    assert "cancel_order" not in names
    assert "preflight" not in names
    source = Path(inspect.getfile(PublicReadOnly)).read_text()
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PublicReadOnly"]
    defined = {node.name for node in classes[0].body if isinstance(node, ast.FunctionDef)}
    assert defined == {
        "__init__",
        "_send",
        "exchange_token",
        "list_accounts",
        "get_portfolio",
        "get_quotes",
    }


def test_burst_stays_at_or_below_eight_per_second() -> None:
    bucket = TokenBucket(rate_per_sec=8.0, capacity=8.0)
    times = [bucket.acquire(now=0.0) for _ in range(20)]
    assert times[:8] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert times[8] == 1.000000001
    assert times[15] == 1.000000001
    assert times[16] == 2.000000002
    assert times[19] == 2.000000002
    for stamp in times:
        window = [item for item in times if stamp - 1.0 <= item <= stamp]
        assert len(window) <= 8

from __future__ import annotations

from typing import Protocol

import httpx

from samar_brokers.limiter import TokenBucket
from samar_brokers.types import Account, PortfolioSnapshot, Position, Quote

AUTH_URL = "https://api.public.com/userapiauthservice/personal/access-tokens"
GATEWAY = "https://api.public.com/userapigateway"


class Clock(Protocol):
    def __call__(self) -> float:
        """Monotonic seconds."""
        ...


class PublicReadOnly:
    """Personal-key reads. This class has no order method."""

    def __init__(
        self,
        secret: str,
        client: httpx.Client,
        bucket: TokenBucket | None = None,
        *,
        auth_url: str = AUTH_URL,
        gateway: str = GATEWAY,
    ) -> None:
        if not secret.strip():
            raise ValueError("Public secret is required")
        self._secret = secret
        self._client = client
        self._bucket = bucket or TokenBucket()
        self._token: str | None = None
        self._auth_url = auth_url
        self._gateway = gateway

    def _send(self, method: str, url: str, json_body: object | None = None) -> httpx.Response:
        self._bucket.acquire()
        headers: dict[str, str] = {}
        if self._token is not None and self._auth_url not in url:
            headers["Authorization"] = f"Bearer {self._token}"
        response = self._client.request(method, url, json=json_body, headers=headers)
        response.raise_for_status()
        return response

    def exchange_token(self) -> None:
        response = self._send(
            "POST",
            self._auth_url,
            {"secret": self._secret, "validityInMinutes": 15},
        )
        body = _object(response.json())
        token = body.get("accessToken")
        if not isinstance(token, str):
            raise ValueError("Public token response missing accessToken")
        self._token = token

    def list_accounts(self) -> list[Account]:
        if self._token is None:
            self.exchange_token()
        response = self._send("GET", f"{self._gateway}/trading/account")
        body = _object(response.json())
        accounts: list[Account] = []
        for row in _objects(_list(body.get("accounts"))):
            account_id = row.get("accountId")
            if isinstance(account_id, str) and account_id:
                nickname = row.get("nickname")
                accounts.append(
                    Account(
                        account_id=account_id,
                        nickname=nickname if isinstance(nickname, str) else "",
                    )
                )
        return accounts

    def get_portfolio(self, account_id: str) -> PortfolioSnapshot:
        if self._token is None:
            self.exchange_token()
        response = self._send("GET", f"{self._gateway}/trading/{account_id}/portfolio/v2")
        body = _object(response.json())
        positions: list[Position] = []
        for row in _objects(_list(body.get("positions"))):
            instrument = row.get("instrument")
            symbol = ""
            if isinstance(instrument, dict):
                raw_symbol = _object(instrument).get("symbol")
                symbol = raw_symbol if isinstance(raw_symbol, str) else ""
            elif isinstance(row.get("symbol"), str):
                raw = row.get("symbol")
                symbol = raw if isinstance(raw, str) else ""
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=_float(row.get("quantity")),
                    market_value=_float(row.get("currentValue", row.get("marketValue"))),
                )
            )
        equity = body.get("equity", body.get("totalAccountValue"))
        cash = body.get("buyingPower", body.get("cash"))
        return PortfolioSnapshot(
            account_id=account_id,
            equity=_float(equity),
            cash=_float(cash),
            positions=positions,
        )

    def get_quotes(self, account_id: str, symbols: list[str]) -> list[Quote]:
        if self._token is None:
            self.exchange_token()
        response = self._send(
            "POST",
            f"{self._gateway}/marketdata/{account_id}/quotes",
            {"instruments": [{"symbol": symbol, "type": "EQUITY"} for symbol in symbols]},
        )
        body = _object(response.json())
        quotes: list[Quote] = []
        for row in _objects(_list(body.get("quotes"))):
            symbol = row.get("symbol")
            if isinstance(symbol, str):
                quotes.append(Quote(symbol=symbol, last=_float(row.get("last"))))
        return quotes


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    parsed: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(key, str):
            parsed[key] = item
    return parsed


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(value)


def _objects(values: list[object]) -> list[dict[str, object]]:
    return [_object(value) for value in values if isinstance(value, dict)]


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)

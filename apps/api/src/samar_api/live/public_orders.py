from __future__ import annotations

import os
from typing import Protocol

import httpx
from samar_brokers.limiter import TokenBucket
from samar_brokers.public_readonly import AUTH_URL, GATEWAY

from samar_api.live.types import Held


class Clock(Protocol):
    def __call__(self) -> float:
        """Monotonic seconds."""
        ...


class BrokerError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BrokerRejected(BrokerError):
    pass


class BrokerView(Protocol):
    def snapshot(self) -> AccountState:
        """Read permission, buying power, and positions."""
        ...

    def quote(self, account_id: str, symbol: str) -> float:
        """Last trade for one equity."""
        ...

    def preflight(self, account_id: str, body: dict[str, object]) -> None:
        """Validate an order before it is sent."""
        ...

    def place_order(self, account_id: str, body: dict[str, object]) -> str:
        """Submit one limit order. The same body is safe to retry."""
        ...

    def cancel_order(self, account_id: str, order_id: str) -> None:
        """Ask the broker to cancel one order."""
        ...


class AccountState:
    def __init__(
        self,
        account_id: str,
        permission: str,
        buying_power: float,
        equity: float,
        positions: tuple[Held, ...],
        *,
        settled_cash: float | None = None,
    ) -> None:
        self.account_id = account_id
        self.permission = permission
        self.buying_power = buying_power
        self.equity = equity
        self.positions = positions
        self.settled_cash = settled_cash


class PublicOrders:
    """The only HTTP client that posts orders."""

    def __init__(
        self,
        secret: str,
        client: httpx.Client,
        bucket: TokenBucket | None = None,
        *,
        auth_url: str | None = None,
        gateway: str | None = None,
    ) -> None:
        if not secret.strip():
            raise ValueError("Public secret is required")
        self._secret = secret
        self._client = client
        self._bucket = bucket or TokenBucket()
        self._token: str | None = None
        self._auth_url = auth_url or os.environ.get("SAMAR_PUBLIC_AUTH_URL", AUTH_URL)
        self._gateway = gateway or os.environ.get("SAMAR_PUBLIC_GATEWAY", GATEWAY)

    def snapshot(self) -> AccountState:
        self._ensure_token()
        response = self._send("GET", f"{self._gateway}/trading/account")
        body = _object(response.json())
        accounts = [row for row in _objects(_list(body.get("accounts"))) if isinstance(row.get("accountId"), str)]
        if not accounts:
            raise BrokerError("no Public.com account")
        account = accounts[0]
        account_id = account.get("accountId")
        if not isinstance(account_id, str) or not account_id:
            raise BrokerError("no Public.com account")
        permission = "trade" if account.get("tradePermissions") == "BUY_AND_SELL" else "read_only"
        portfolio = self._send("GET", f"{self._gateway}/trading/{account_id}/portfolio/v2")
        book = _object(portfolio.json())
        positions = tuple(_position(row) for row in _objects(_list(book.get("positions"))))
        buying_power, settled_cash, equity = _balances(book)
        return AccountState(
            account_id=account_id,
            permission=permission,
            buying_power=buying_power,
            equity=equity,
            positions=tuple(position for position in positions if position.quantity != 0),
            settled_cash=settled_cash,
        )

    def quote(self, account_id: str, symbol: str) -> float:
        self._ensure_token()
        response = self._send(
            "POST",
            f"{self._gateway}/marketdata/{account_id}/quotes",
            {"instruments": [{"symbol": symbol, "type": "EQUITY"}]},
        )
        body = _object(response.json())
        for row in _objects(_list(body.get("quotes"))):
            if row.get("symbol") == symbol:
                last = _float(row.get("last"))
                if last > 0:
                    return last
        raise BrokerError(f"no quote for {symbol}")

    def preflight(self, account_id: str, body: dict[str, object]) -> None:
        self._ensure_token()
        self._send("POST", f"{self._gateway}/trading/{account_id}/preflight/single-leg", body)

    def place_order(self, account_id: str, body: dict[str, object]) -> str:
        self._ensure_token()
        response = self._send("POST", f"{self._gateway}/trading/{account_id}/order", body)
        payload = _object(response.json())
        order_id = payload.get("orderId")
        if not isinstance(order_id, str) or not order_id:
            raise BrokerError("place response missing orderId")
        return order_id

    def cancel_order(self, account_id: str, order_id: str) -> None:
        self._ensure_token()
        self._send("DELETE", f"{self._gateway}/trading/{account_id}/order/{order_id}")

    def get_order(self, account_id: str, order_id: str) -> str | None:
        self._ensure_token()
        try:
            response = self._send("GET", f"{self._gateway}/trading/{account_id}/order/{order_id}")
        except BrokerError as exc:
            if exc.status == 404:
                return None
            raise
        body = _object(response.json())
        status = body.get("orderStatus") or body.get("status")
        return str(status) if isinstance(status, str) and status else "unknown"

    def _ensure_token(self) -> None:
        if self._token is not None:
            return
        response = self._send(
            "POST",
            self._auth_url,
            {"secret": self._secret, "validityInMinutes": 15},
        )
        body = _object(response.json())
        token = body.get("accessToken")
        if not isinstance(token, str) or not token:
            raise BrokerError("Public token response missing accessToken")
        self._token = token

    def _send(self, method: str, url: str, json_body: object | None = None) -> httpx.Response:
        self._bucket.acquire()
        headers: dict[str, str] = {}
        if self._token is not None and self._auth_url not in url:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._client.request(method, url, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            raise BrokerError("broker error") from exc
        if response.status_code == 400:
            raise BrokerRejected("broker rejected the order", status=400)
        if response.status_code >= 400:
            raise BrokerError("broker error", status=response.status_code)
        return response


def order_body(order_id: str, symbol: str, side: str, quantity: int, limit_price: float) -> dict[str, object]:
    return {
        "orderId": order_id,
        "instrument": {"symbol": symbol, "type": "EQUITY"},
        "orderSide": side,
        "orderType": "LIMIT",
        "expiration": {"timeInForce": "DAY"},
        "quantity": str(quantity),
        "limitPrice": f"{limit_price:.2f}",
        "equityMarketSession": "CORE",
        "useMargin": False,
    }


def preflight_body(body: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in body.items() if key != "orderId"}


def _balances(book: dict[str, object]) -> tuple[float, float | None, float]:
    raw = book.get("buyingPower")
    settled: float | None = None
    if isinstance(raw, dict):
        parsed = _object(raw)
        buying = _float(parsed.get("buyingPower"))
        if parsed.get("cashOnlyBuyingPower") is not None:
            settled = _float(parsed.get("cashOnlyBuyingPower"))
    else:
        buying = _float(raw if raw is not None else book.get("cash"))
    equity_raw = book.get("equity")
    if isinstance(equity_raw, list):
        equity = sum(_float(_object(item).get("value")) for item in equity_raw if isinstance(item, dict))
    elif equity_raw is not None:
        equity = _float(equity_raw)
    else:
        equity = _float(book.get("totalAccountValue"))
    return buying, settled, equity


def _position(row: dict[str, object]) -> Held:
    instrument = row.get("instrument")
    symbol = ""
    kind = "EQUITY"
    if isinstance(instrument, dict):
        parsed = _object(instrument)
        raw_symbol = parsed.get("symbol")
        raw_type = parsed.get("type")
        symbol = raw_symbol if isinstance(raw_symbol, str) else ""
        kind = raw_type if isinstance(raw_type, str) else "EQUITY"
    elif isinstance(row.get("symbol"), str):
        raw = row.get("symbol")
        symbol = raw if isinstance(raw, str) else ""
    quantity = _float(row.get("quantity"))
    return Held(symbol=symbol, quantity=quantity, instrument_type=kind, market_value=_market_value(row, quantity))


def _market_value(row: dict[str, object], quantity: float) -> float | None:
    """None when the broker gives no parseable value, so the capital cap refuses instead of counting zero."""
    current = _number(row.get("currentValue"))
    if current is not None:
        return current
    last = row.get("lastPrice")
    price = _number(_object(last).get("lastPrice")) if isinstance(last, dict) else None
    return None if price is None else quantity * price


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BrokerError("expected a JSON object")
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
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from samar_api.app import create_app
from samar_api.live import book as book_module
from samar_api.live.book import LiveBook
from samar_api.live.limits import ALLOWLIST, AUTO_PHRASE, ENABLE_PHRASE, evaluate, sell_proceeds_unsettled, whole_shares
from samar_api.live.signal import strategy_intent
from samar_api.live.types import GuardContext, Held, Limits, OrderIntent, SourceChoice
from samar_api.service import AppState
from samar_data.market import MemoryMarketData
from samar_engine.core.events import Bar
from samar_engine.dsl import StrategySpec
from samar_worker.__main__ import cycle_once

pytestmark = pytest.mark.enable_socket

OPEN = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
CLOSED = datetime(2026, 10, 15, 21, 0, tzinfo=UTC)
PUBLIC = "pub-ABCDEFGHIJKL"
MODEL_KEY = "sk-" + ("A" * 20)
ORDER_ID = "11111111-1111-4111-8111-111111111111"
PLACE = {
    "orderId": ORDER_ID,
    "instrument": {"symbol": "AAPL", "type": "EQUITY"},
    "orderSide": "BUY",
    "orderType": "LIMIT",
    "expiration": {"timeInForce": "DAY"},
    "quantity": "1",
    "limitPrice": "20.00",
    "equityMarketSession": "CORE",
    "useMargin": False,
}


def _bars() -> list[Bar]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    return [
        Bar(
            symbol="AAPL",
            timestamp=start + timedelta(days=index),
            open=20.0,
            high=21.0,
            low=19.0,
            close=20.0,
            volume=1_000,
        )
        for index in range(3)
    ]


class Script:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []
        self.permission: str | None = "BUY_AND_SELL"
        self.positions: list[dict[str, object]] = []
        self.buying_power = "250.00"
        self.cash_only: str | None = None
        self.equity = "250.00"
        self.quote = "20.00"
        self.place_status = 200
        self.place_limit = 99
        self.model_text = json.dumps(
            {"symbol": "AAPL", "side": "BUY", "quantity": 1, "limit_price": 20, "reason": "test ticket"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, str(request.url), request.content))
        url = str(request.url)
        if url.endswith("/access-tokens"):
            return httpx.Response(200, json={"accessToken": "tok-live"})
        if url.endswith("/trading/account"):
            account: dict[str, object] = {"accountId": "acc-1", "accountType": "BROKERAGE"}
            if self.permission is not None:
                account["tradePermissions"] = self.permission
            return httpx.Response(200, json={"accounts": [account]})
        if url.endswith("/portfolio/v2"):
            buying: object = self.buying_power
            if self.cash_only is not None:
                buying = {"buyingPower": self.buying_power, "cashOnlyBuyingPower": self.cash_only}
            return httpx.Response(
                200,
                json={
                    "buyingPower": buying,
                    "equity": self.equity,
                    "positions": self.positions,
                },
            )
        if url.endswith("/quotes"):
            return httpx.Response(200, json={"quotes": [{"symbol": "AAPL", "last": self.quote}]})
        if url.endswith("/preflight/single-leg"):
            return httpx.Response(200, json={"estimatedCost": "20.00"})
        if request.method == "DELETE" and "/order/" in url:
            return httpx.Response(200, json={"orderId": url.rsplit("/", 1)[-1]})
        if request.method == "POST" and url.endswith("/order"):
            placed = [call for call in self.calls if call[0] == "POST" and call[1].endswith("/order")]
            status = self.place_status if len(placed) <= self.place_limit else 200
            if status != 200:
                return httpx.Response(status, json={"message": "rejected"})
            body = json.loads(request.content)
            return httpx.Response(200, json={"orderId": body["orderId"]})
        if "chat/completions" in url or url.endswith("/messages"):
            if "api.anthropic.com" in url or url.endswith("/messages"):
                return httpx.Response(200, json={"content": [{"type": "text", "text": self.model_text}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": self.model_text}}]})
        return httpx.Response(500, json={"message": "unexpected"})

    @property
    def places(self) -> list[bytes]:
        return [body for method, url, body in self.calls if method == "POST" and url.endswith("/order")]

    @property
    def preflights(self) -> list[bytes]:
        return [body for _method, url, body in self.calls if url.endswith("/preflight/single-leg")]

    @property
    def cancels(self) -> list[str]:
        return [url for method, url, _body in self.calls if method == "DELETE"]


def _state(script: Script, path: str = ":memory:") -> AppState:
    return AppState(
        path,
        MemoryMarketData({"AAPL": _bars()}),
        kek=b"k" * 32,
        http=httpx.Client(transport=httpx.MockTransport(script)),
    )


def _session(script: Script, path: str = ":memory:") -> tuple[TestClient, AppState, str, LiveBook]:
    state = _state(script, path)
    client = TestClient(create_app(state))
    registered = client.post("/auth/register", json={"email": "demo@example.com", "password": "demo-password-1"})
    assert registered.status_code == 200
    client.headers["Authorization"] = f"Bearer {registered.json()['token']}"
    user_id = state.user_from_authorization(client.headers["Authorization"]).id
    state.save_key(user_id, "public_com", PUBLIC, True)
    book = LiveBook(state.conn, state.http, state.read_key, state.market)
    return client, state, user_id, book


def _arm(book: LiveBook, user_id: str) -> None:
    status = book.enable(user_id, ENABLE_PHRASE, OPEN)
    assert status.enabled is True
    assert status.mode == "approve"
    status = book.enable_auto(user_id, AUTO_PHRASE, OPEN)
    assert status.mode == "auto"


def _ok_intent() -> OrderIntent:
    return OrderIntent(
        symbol="AAPL",
        side="BUY",
        quantity=1,
        limit_price=20,
        reason="one share",
        model="test",
    )


def _ok_ctx() -> GuardContext:
    return GuardContext(
        live_enabled=True,
        limits=Limits(),
        buying_power=250,
        positions=(),
        day_pnl=0,
        orders_today=0,
        now=OPEN,
        allowlist=ALLOWLIST,
    )


def test_each_limit_rejects_with_its_reason() -> None:
    cases: list[tuple[str, OrderIntent, GuardContext, bool]] = []
    off = _ok_ctx().model_copy(update={"live_enabled": False})
    cases.append(("live mode is off", _ok_intent(), off, False))
    cases.append(
        ("symbol is not on the allowlist", _ok_intent().model_copy(update={"symbol": "ZZZZ"}), _ok_ctx(), False)
    )
    cases.append(
        (
            "options are not allowed",
            _ok_intent().model_copy(update={"symbol": "AAPL 251219C00200000"}),
            _ok_ctx(),
            False,
        )
    )
    cases.append(("crypto is not allowed", _ok_intent().model_copy(update={"symbol": "BTC-USD"}), _ok_ctx(), False))
    cases.append(("shorting is not allowed", _ok_intent().model_copy(update={"side": "SELL"}), _ok_ctx(), False))
    cases.append(("market is closed", _ok_intent(), _ok_ctx().model_copy(update={"now": CLOSED}), False))
    wide = Limits(capital_cap=1000, max_order_dollars=200, max_orders_per_day=4, daily_loss_stop=50)
    cases.append(
        (
            "order exceeds the per-order cap",
            _ok_intent().model_copy(update={"quantity": 2, "limit_price": 150}),
            _ok_ctx().model_copy(update={"limits": wide, "buying_power": 1000}),
            False,
        )
    )
    capital = Limits(capital_cap=200, max_order_dollars=500, max_orders_per_day=4, daily_loss_stop=50)
    cases.append(
        (
            "order exceeds the capital cap",
            _ok_intent().model_copy(update={"quantity": 2, "limit_price": 150}),
            _ok_ctx().model_copy(update={"limits": capital, "buying_power": 1000}),
            False,
        )
    )
    power = Limits(capital_cap=500, max_order_dollars=500, max_orders_per_day=4, daily_loss_stop=50)
    cases.append(
        (
            "order exceeds buying power",
            _ok_intent().model_copy(update={"quantity": 2, "limit_price": 80}),
            _ok_ctx().model_copy(update={"limits": power, "buying_power": 100}),
            False,
        )
    )
    cases.append(("daily order limit reached", _ok_intent(), _ok_ctx().model_copy(update={"orders_today": 4}), False))
    minute = _ok_ctx().model_copy(update={"orders_last_minute": 2})
    cases.append(("model order rate limit reached", _ok_intent(), minute, False))
    open_day = _ok_ctx().model_copy(
        update={"orders_today": 9, "limits": Limits(max_orders_per_day=None, max_orders_per_minute=2)}
    )
    assert evaluate(_ok_intent(), open_day).ok is True
    stopped = _ok_ctx().model_copy(update={"day_pnl": -50})
    cases.append(("daily loss stop is hit", _ok_intent(), stopped, True))
    cases.append(("limit price is required", _ok_intent().model_copy(update={"limit_price": 0}), _ok_ctx(), False))
    cases.append(("quantity must be a whole share", _ok_intent().model_copy(update={"quantity": 0}), _ok_ctx(), False))
    settled = _ok_ctx().model_copy(update={"buying_power": 100, "settled_cash": 40})
    wide_caps = Limits(capital_cap=500, max_order_dollars=500, max_orders_per_day=4, daily_loss_stop=50)
    cases.append(
        (
            "order exceeds settled cash",
            _ok_intent().model_copy(update={"quantity": 3, "limit_price": 20}),
            settled.model_copy(update={"limits": wide_caps}),
            False,
        )
    )
    cases.append(("margin is not allowed", _ok_intent().model_copy(update={"use_margin": True}), _ok_ctx(), False))
    for reason, intent, ctx, halt in cases:
        result = evaluate(intent, ctx)
        assert result.ok is False
        assert result.reason == reason
        assert result.halt is halt
    assert evaluate(_ok_intent(), _ok_ctx()).ok is True
    with pytest.raises(ValueError, match="quantity must be a whole share"):
        whole_shares(1.5)


def test_fractional_ticket_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(symbol="AAPL", side="BUY", quantity=1.5, limit_price=20, reason="no")  # type: ignore[arg-type]


def test_readonly_key_cannot_enable() -> None:
    script = Script()
    script.permission = None
    _client, _state, user_id, book = _session(script)
    with pytest.raises(ValueError, match="this Public key cannot trade"):
        book.enable(user_id, ENABLE_PHRASE, OPEN)
    assert book.status(user_id).enabled is False
    assert book.status(user_id).permission == "read_only"


def test_auto_stays_off_until_its_own_phrase() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    with pytest.raises(ValueError, match="confirmation phrase does not match"):
        book.enable_auto(user_id, "trade it", OPEN)
    assert book.status(user_id).mode == "approve"
    assert book.status(user_id).banner == "live"


def test_place_body_preflight_and_idempotent_retry() -> None:
    script = Script()
    _client, state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    ticket = book.propose(
        user_id,
        OrderIntent(symbol="AAPL", side="BUY", quantity=1, limit_price=20, reason="one share", model="manual"),
        OPEN,
    )
    state.conn.execute("UPDATE live_tickets SET order_id = ? WHERE id = ?", (ORDER_ID, ticket.id))
    state.conn.commit()
    approved = book.approve(user_id, ticket.id, OPEN)
    assert approved.status == "sent"
    assert len(script.preflights) == 1
    assert len(script.places) == 1
    assert json.loads(script.preflights[0]) == {key: value for key, value in PLACE.items() if key != "orderId"}
    assert json.loads(script.places[0]) == PLACE
    preflight_at = next(index for index, call in enumerate(script.calls) if call[1].endswith("/preflight/single-leg"))
    place_at = next(
        index for index, call in enumerate(script.calls) if call[0] == "POST" and call[1].endswith("/order")
    )
    assert preflight_at < place_at
    state.conn.execute("UPDATE live_tickets SET status = 'pending' WHERE id = ?", (ticket.id,))
    state.conn.commit()
    again = book.approve(user_id, ticket.id, OPEN)
    assert again.status == "sent"
    assert len(script.places) == 1
    assert any(row.detail == "retry reused the order id" for row in book.audit(user_id))


def test_expired_ticket_places_nothing() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    ticket = book.propose(
        user_id,
        OrderIntent(symbol="AAPL", side="BUY", quantity=1, limit_price=20, reason="one share", model="manual"),
        OPEN,
    )
    with pytest.raises(ValueError, match="ticket expired"):
        book.approve(user_id, ticket.id, OPEN + timedelta(minutes=6))
    assert script.places == []


def test_kill_switch_cancels_and_disables() -> None:
    script = Script()
    _client, state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    ticket = book.propose(
        user_id,
        OrderIntent(symbol="AAPL", side="BUY", quantity=1, limit_price=20, reason="one share", model="manual"),
        OPEN,
    )
    book.approve(user_id, ticket.id, OPEN)
    before = [row.id for row in book.audit(user_id)]
    status = book.kill(user_id, OPEN)
    assert status.enabled is False
    assert status.banner == "paper"
    assert status.halted_reason == "kill switch"
    order_id = json.loads(script.places[0])["orderId"]
    assert any(url.endswith(f"/order/{order_id}") for url in script.cancels)
    order = state.conn.execute("SELECT status FROM live_orders WHERE user_id = ?", (user_id,)).fetchone()
    assert order["status"] == "cancelled"
    after = [row.id for row in book.audit(user_id)]
    assert all(row_id in after for row_id in before)
    assert len(after) == len(before) + 1


def test_auto_cycle_places_one_and_market_closed_places_none() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    intent = OrderIntent(symbol="AAPL", side="BUY", quantity=1, limit_price=20, reason="auto", model="script")

    def propose() -> OrderIntent:
        return intent

    assert book.run_cycle(user_id, OPEN, propose) == 1
    assert len(script.places) == 1
    assert book.run_cycle(user_id, OPEN, propose) == 0
    assert len(script.places) == 1

    def boom() -> OrderIntent:
        raise AssertionError("closed market must not ask for an order")

    assert book.run_cycle(user_id, CLOSED, boom) == 0
    assert len(script.places) == 1


def test_worker_cycle_places_without_a_browser() -> None:
    script = Script()
    _client, state, user_id, book = _session(script)
    _arm(book, user_id)
    state.save_key(user_id, "openai", MODEL_KEY, True)
    book.set_source(user_id, SourceChoice(source="model", provider="openai", model="gpt-4o-mini"), OPEN)
    jobs, placed = cycle_once(state, OPEN)
    assert jobs == 0
    assert placed == 1
    assert len(script.places) == 1
    model_calls = [body for _method, url, body in script.calls if "api.openai.com" in url]
    assert model_calls
    for body in model_calls:
        assert PUBLIC.encode() not in body
        assert b"tok-live" not in body


def test_strategy_sizes_to_the_per_order_cap() -> None:
    spec = StrategySpec.model_validate(
        {
            "name": "always",
            "universe": ["AAPL"],
            "rules": [
                {
                    "when": {
                        "kind": "compare",
                        "left": {"kind": "indicator", "name": "price", "ticker": "AAPL"},
                        "op": ">",
                        "right": {"kind": "const", "value": 0},
                    },
                    "then": {"kind": "buy", "ticker": "AAPL", "amount": {"kind": "shares", "value": 100}},
                }
            ],
        }
    )
    intent = strategy_intent(spec, _bars(), 20, Limits(), 0)
    assert intent is not None
    assert intent.quantity == 10
    assert intent.limit_price == 20
    script = Script()
    _client, state, user_id, book = _session(script)
    created = state.create_strategy(user_id, spec)
    _arm(book, user_id)
    book.set_source(user_id, SourceChoice(source="strategy", strategy_id=created.id), OPEN)
    assert book.run_cycle(user_id, OPEN, None) == 1
    body = json.loads(script.places[0])
    assert body["quantity"] == "10"
    assert body["limitPrice"] == "20.00"
    assert body["useMargin"] is False


def test_guardrail_reject_does_not_count_as_a_broker_rejection() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)

    def huge() -> OrderIntent:
        return OrderIntent(symbol="AAPL", side="BUY", quantity=50, limit_price=20, reason="too big", model="script")

    assert book.run_cycle(user_id, OPEN, huge) == 0
    assert script.places == []
    assert book.status(user_id).reject_streak == 0
    assert book.status(user_id).enabled is True


def test_broker_error_halts_and_cancels() -> None:
    script = Script()
    _client, state, user_id, book = _session(script)
    _arm(book, user_id)
    assert book.run_cycle(user_id, OPEN, _ok_intent) == 1
    script.place_status = 500
    ford = _ok_intent().model_copy(update={"symbol": "F"})
    assert book.run_cycle(user_id, OPEN + timedelta(minutes=1), lambda: ford) == 0
    assert book.status(user_id).enabled is False
    assert book.status(user_id).halted_reason == "broker error"
    order = state.conn.execute("SELECT id, status FROM live_orders WHERE symbol = 'AAPL'").fetchone()
    assert order["status"] == "cancelled"
    assert any(order["id"] in url for url in script.cancels)


def test_three_rejections_halt() -> None:
    script = Script()
    script.place_status = 400
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    symbols = ["AAPL", "F", "T"]
    for index, symbol in enumerate(symbols):
        intent = OrderIntent(symbol=symbol, side="BUY", quantity=1, limit_price=20, reason="try", model="script")
        assert book.run_cycle(user_id, OPEN + timedelta(minutes=index), lambda intent=intent: intent) == 0
    assert len(script.places) == 3
    assert book.status(user_id).enabled is False
    assert book.status(user_id).halted_reason == "repeated rejections"


def test_unexpected_position_halts_before_an_order() -> None:
    script = Script()
    script.positions = [{"instrument": {"symbol": "BTC-USD", "type": "CRYPTO"}, "quantity": "1"}]
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    assert book.run_cycle(user_id, OPEN, _ok_intent) == 0
    assert script.places == []
    assert book.status(user_id).halted_reason == "unexpected position"
    script = Script()
    script.positions = [{"instrument": {"symbol": "AAPL", "type": "EQUITY"}, "quantity": "-1"}]
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    assert book.run_cycle(user_id, OPEN, _ok_intent) == 0
    assert book.status(user_id).halted_reason == "unexpected position"
    assert script.places == []


def test_daily_loss_stop_halts() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    book.set_source(user_id, SourceChoice(source="off"), OPEN)
    assert book.run_cycle(user_id, OPEN, None) == 0
    script.equity = "190.00"
    assert book.run_cycle(user_id, OPEN + timedelta(hours=1), None) == 0
    assert book.status(user_id).enabled is False
    assert book.status(user_id).halted_reason == "daily loss stop is hit"
    assert script.places == []


def test_invalid_model_output_does_not_halt() -> None:
    script = Script()
    script.model_text = "not json"
    _client, state, user_id, book = _session(script)
    _arm(book, user_id)
    state.save_key(user_id, "openai", MODEL_KEY, True)
    book.set_source(user_id, SourceChoice(source="model", provider="openai", model="gpt-4o-mini"), OPEN)
    assert book.run_cycle(user_id, OPEN, None) == 0
    assert book.status(user_id).enabled is True
    assert any(row.action == "model_invalid" for row in book.audit(user_id))
    assert script.places == []


def test_unsettled_sale_cannot_fund_a_rebuy() -> None:
    sold = OPEN
    same_day = OPEN + timedelta(hours=4)
    next_day = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)
    assert sell_proceeds_unsettled(sold, same_day) is True
    assert sell_proceeds_unsettled(sold, next_day) is False
    script = Script()
    _client, state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    state.conn.execute(
        "UPDATE live_settings SET buying_power = 100, settled_cash = NULL WHERE user_id = ?",
        (user_id,),
    )
    state.conn.execute(
        """INSERT INTO live_tickets
        (id, user_id, symbol, side, qty, limit_price, est_cost, reason, model, status, created_at, expires_at)
        VALUES ('tkt_sell', ?, 'AAPL', 'SELL', 1, 30, 30, 'sold', 'manual', 'sent', ?, ?)""",
        (user_id, sold.isoformat(), (sold + timedelta(minutes=5)).isoformat()),
    )
    state.conn.execute(
        """INSERT INTO live_orders
        (id, user_id, ticket_id, symbol, side, qty, limit_price, status, created_at)
        VALUES ('ord_sell', ?, 'tkt_sell', 'AAPL', 'SELL', 1, 30, 'submitted', ?)""",
        (user_id, sold.isoformat()),
    )
    state.conn.commit()
    book.set_limits(user_id, Limits(capital_cap=100, max_order_dollars=100, max_orders_per_day=4), same_day)
    with pytest.raises(ValueError, match="order exceeds settled cash"):
        book.propose(
            user_id,
            OrderIntent(symbol="F", side="BUY", quantity=4, limit_price=20, reason="rebuy", model="manual"),
            same_day,
        )
    ticket = book.propose(
        user_id,
        OrderIntent(symbol="F", side="BUY", quantity=3, limit_price=20, reason="within settled", model="manual"),
        same_day,
    )
    assert ticket.est_cost == 60
    later = book.propose(
        user_id,
        OrderIntent(symbol="T", side="BUY", quantity=4, limit_price=20, reason="after settlement", model="manual"),
        next_day,
    )
    assert later.est_cost == 80


def test_cash_only_buying_power_is_the_settled_ceiling() -> None:
    script = Script()
    script.cash_only = "40.00"
    script.buying_power = "100.00"
    _client, _state, user_id, book = _session(script)
    status = book.enable(user_id, ENABLE_PHRASE, OPEN)
    assert status.buying_power == 100
    book.set_limits(user_id, Limits(capital_cap=100, max_order_dollars=100), OPEN)
    with pytest.raises(ValueError, match="order exceeds settled cash"):
        book.propose(
            user_id,
            OrderIntent(symbol="AAPL", side="BUY", quantity=3, limit_price=20, reason="too much", model="manual"),
            OPEN,
        )


def test_unlimited_day_still_stops_a_looping_model() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    book.set_limits(
        user_id,
        Limits(capital_cap=200, max_order_dollars=200, max_orders_per_day=None, max_orders_per_minute=2),
        OPEN,
    )
    assert book.status(user_id).max_orders_per_day is None
    symbols = ["AAPL", "F", "T", "KO", "PFE"]
    for index, symbol in enumerate(symbols):
        intent = OrderIntent(symbol=symbol, side="BUY", quantity=1, limit_price=20, reason="day", model="day")
        placed = book.run_cycle(user_id, OPEN + timedelta(seconds=70 * index), lambda intent=intent: intent)
        assert placed == 1
    assert len(script.places) == 5
    later = OPEN + timedelta(hours=2)
    spy = OrderIntent(symbol="SPY", side="BUY", quantity=1, limit_price=20, reason="loop", model="loop")
    msft = OrderIntent(symbol="MSFT", side="BUY", quantity=1, limit_price=20, reason="loop", model="loop")
    nvda = OrderIntent(symbol="NVDA", side="BUY", quantity=1, limit_price=20, reason="loop", model="loop")
    assert book.run_cycle(user_id, later, lambda: spy) == 1
    assert book.run_cycle(user_id, later + timedelta(seconds=20), lambda: msft) == 1
    assert book.run_cycle(user_id, later + timedelta(seconds=40), lambda: nvda) == 0
    assert book.status(user_id).enabled is True
    other = OrderIntent(symbol="AMD", side="BUY", quantity=1, limit_price=20, reason="other", model="other")
    assert book.run_cycle(user_id, later + timedelta(seconds=50), lambda: other) == 1
    assert len(script.places) == 8


def test_capital_cap_cannot_exceed_buying_power() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    with pytest.raises(ValueError, match="capital cap cannot exceed buying power"):
        book.set_limits(user_id, Limits(capital_cap=300, max_order_dollars=200), OPEN)


def test_live_routes_require_the_phrases() -> None:
    script = Script()
    client, _state, _user, _book = _session(script)
    refused = client.post("/live/enable", json={"phrase": "please"})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "confirmation phrase does not match"
    enabled = client.post("/live/enable", json={"phrase": ENABLE_PHRASE})
    assert enabled.status_code == 200
    assert enabled.json()["banner"] == "live"
    auto = client.post("/live/auto", json={"phrase": AUTO_PHRASE})
    assert auto.status_code == 200
    assert auto.json()["banner"] == "auto"
    killed = client.post("/live/kill")
    assert killed.status_code == 200
    assert killed.json()["banner"] == "paper"
    fractional = client.post(
        "/live/tickets",
        json={"symbol": "AAPL", "side": "BUY", "quantity": 1.5, "limit_price": 20, "reason": "no"},
    )
    assert fractional.status_code == 422
    assert "UPDATE live_audit" not in open("apps/api/src/samar_api/live/book.py", encoding="utf-8").read()
    assert "DELETE FROM live_audit" not in open("apps/api/src/samar_api/live/book.py", encoding="utf-8").read()
    _ = uuid.UUID(ORDER_ID)
    _ = Held(symbol="AAPL", quantity=1)


def test_capital_cap_totals_exposure_across_buys() -> None:
    script = Script()
    script.buying_power = "2000.00"
    script.equity = "2000.00"
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    book.set_limits(user_id, Limits(capital_cap=200, max_order_dollars=200, max_orders_per_day=None), OPEN)
    symbols = ["AAPL", "F", "T", "KO", "PFE", "INTC"]
    for index, symbol in enumerate(symbols):
        intent = OrderIntent(symbol=symbol, side="BUY", quantity=9, limit_price=20, reason="fill", model=f"m{index}")
        book.run_cycle(user_id, OPEN + timedelta(seconds=70 * index), lambda intent=intent: intent)
    bodies = [json.loads(body) for body in script.places]
    spent = sum(int(body["quantity"]) * float(body["limitPrice"]) for body in bodies)
    assert spent <= 200
    assert len(bodies) == 1
    assert any(row.detail == "order exceeds the capital cap" for row in book.audit(user_id))


def test_held_positions_count_against_the_capital_cap() -> None:
    script = Script()
    script.positions = [{"instrument": {"symbol": "AAPL", "type": "EQUITY"}, "quantity": "5", "currentValue": "150.00"}]
    _client, _state, user_id, book = _session(script)
    _arm(book, user_id)
    over = OrderIntent(symbol="F", side="BUY", quantity=3, limit_price=20, reason="over", model="script")
    assert book.run_cycle(user_id, OPEN, lambda: over) == 0
    assert script.places == []
    under = OrderIntent(symbol="F", side="BUY", quantity=2, limit_price=20, reason="under", model="script")
    assert book.run_cycle(user_id, OPEN + timedelta(minutes=1), lambda: under) == 1
    script.positions = [{"instrument": {"symbol": "AAPL", "type": "EQUITY"}, "quantity": "5", "currentValue": "n/a"}]
    small = OrderIntent(symbol="T", side="BUY", quantity=1, limit_price=1, reason="small", model="script")
    assert book.run_cycle(user_id, OPEN + timedelta(minutes=2), lambda: small) == 0
    assert any(row.detail == "position value is unknown" for row in book.audit(user_id))
    capital = Limits(capital_cap=200, max_order_dollars=200)
    ctx = _ok_ctx().model_copy(update={"limits": capital, "buying_power": 1000})
    held = (Held(symbol="AAPL", quantity=5, market_value=150),)
    assert evaluate(_ok_intent(), ctx.model_copy(update={"positions": held})).ok is True
    assert evaluate(_ok_intent(), ctx.model_copy(update={"positions": held, "open_buys": 40})).reason == (
        "order exceeds the capital cap"
    )
    unknown = (Held(symbol="AAPL", quantity=5),)
    assert evaluate(_ok_intent(), ctx.model_copy(update={"positions": unknown})).reason == "position value is unknown"
    sell = _ok_intent().model_copy(update={"side": "SELL", "quantity": 5})
    assert evaluate(sell, ctx.model_copy(update={"positions": unknown, "open_buys": 500})).ok is True


def _pace_evaluate(monkeypatch: pytest.MonkeyPatch, parties: int) -> None:
    """Hold the first guard checks until every racer has reached one."""
    real = book_module.evaluate
    gate = threading.Barrier(parties, timeout=2)
    lock = threading.Lock()
    seen = [0]

    def paced(intent: OrderIntent, ctx: GuardContext) -> object:
        with lock:
            seen[0] += 1
            wait = seen[0] <= parties
        if wait:
            try:
                gate.wait()
            except threading.BrokenBarrierError:
                pass
        return real(intent, ctx)

    monkeypatch.setattr(book_module, "evaluate", paced)


def _race(*jobs: Callable[[], object]) -> list[object]:
    results: list[object] = [None] * len(jobs)

    def run(index: int, job: Callable[[], object]) -> None:
        try:
            results[index] = job()
        except Exception as exc:
            results[index] = exc

    threads = [threading.Thread(target=run, args=(index, job)) for index, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def test_worker_and_check_cannot_send_the_same_order_twice(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script()
    path = str(tmp_path) + "/live.db"
    _client, state, user_id, api_book = _session(script, path)
    _arm(api_book, user_id)
    worker = _state(script, path)
    worker_book = LiveBook(worker.conn, worker.http, worker.read_key, worker.market)
    _pace_evaluate(monkeypatch, 2)
    results = _race(
        lambda: worker_book.run_cycle(user_id, OPEN, _ok_intent),
        lambda: api_book.run_cycle(user_id, OPEN, _ok_intent),
    )
    assert sorted(str(result) for result in results) == ["0", "1"]
    assert len(script.places) == 1
    tickets = state.conn.execute("SELECT status FROM live_tickets WHERE user_id = ?", (user_id,)).fetchall()
    assert [row["status"] for row in tickets] == ["sent"]


def test_two_approvals_of_one_ticket_send_once(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script()
    path = str(tmp_path) + "/live.db"
    _client, state, user_id, book = _session(script, path)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    ticket = book.propose(user_id, _ok_intent(), OPEN)
    second = _state(script, path)
    other = LiveBook(second.conn, second.http, second.read_key, second.market)
    _pace_evaluate(monkeypatch, 2)
    results = _race(lambda: book.approve(user_id, ticket.id, OPEN), lambda: other.approve(user_id, ticket.id, OPEN))
    assert len(script.places) == 1
    assert sum(1 for result in results if isinstance(result, ValueError)) == 1


def test_a_second_ticket_for_a_working_order_is_refused() -> None:
    script = Script()
    _client, _state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    book.propose(user_id, _ok_intent(), OPEN)
    with pytest.raises(ValueError, match="AAPL BUY is already working"):
        book.propose(user_id, _ok_intent(), OPEN)


def test_daily_loss_stop_fires_in_approve_each_mode() -> None:
    script = Script()
    script.buying_power = "2500.00"
    script.equity = "2000.00"
    _client, _state, user_id, book = _session(script)
    book.enable(user_id, ENABLE_PHRASE, OPEN)
    first = book.propose(user_id, _ok_intent(), OPEN)
    assert book.approve(user_id, first.id, OPEN).status == "sent"
    script.equity = "1000.00"
    later = OPEN + timedelta(minutes=30)
    ford = book.propose(user_id, _ok_intent().model_copy(update={"symbol": "F"}), later)
    with pytest.raises(ValueError, match="daily loss stop is hit"):
        book.approve(user_id, ford.id, later)
    assert len(script.places) == 1
    status = book.status(user_id)
    assert status.enabled is False
    assert status.halted_reason == "daily loss stop is hit"

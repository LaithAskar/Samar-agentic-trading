from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from samar_api.app import create_app
from samar_api.arena_run import arena_prompt
from samar_api.service import AppState, resolve_kek
from samar_contracts.models import SecretStatus
from samar_data.market import FixtureMarketData, MemoryMarketData, PreferLocalMarketData
from samar_engine.arena import random_specs
from samar_engine.core.events import Bar
from samar_engine.dsl import StrategySpec

pytestmark = pytest.mark.enable_socket


def _bars() -> list[Bar]:
    start = datetime(2024, 1, 1)
    prices = [(9.0, 9.0), (10.0, 11.0), (10.0, 10.0)]
    return [
        Bar(
            symbol="AAPL",
            timestamp=start + timedelta(days=i),
            open=open_,
            high=max(open_, close),
            low=min(open_, close),
            close=close,
            volume=1_000,
        )
        for i, (open_, close) in enumerate(prices)
    ]


def _fail(request: httpx.Request) -> httpx.Response:
    raise AssertionError(str(request.url))


def _state(handler: httpx.MockTransport | None = None) -> AppState:
    transport = handler or httpx.MockTransport(_fail)
    series = {"AAPL": _bars(), "SPY": _bars()}
    return AppState(":memory:", MemoryMarketData(series), kek=b"k" * 32, http=httpx.Client(transport=transport))


def _client(handler: httpx.MockTransport | None = None) -> TestClient:
    client = TestClient(create_app(_state(handler)))
    registered = client.post(
        "/auth/register",
        json={"email": "demo@example.com", "password": "demo-password-1"},
    )
    assert registered.status_code == 200
    client.headers["Authorization"] = f"Bearer {registered.json()['token']}"
    return client


def _draft_json(call: int) -> dict[str, object]:
    if call == 1:
        payload = {
            "thought": "Draft the SMA and wait.",
            "action": "create_strategy_draft",
            "action_input": {"template": "sma_cross", "ticker": "AAPL"},
            "final": None,
        }
    else:
        payload = {
            "thought": "Answer from the observations.",
            "action": None,
            "action_input": {},
            "final": "Draft is ready for your approval. Nothing is saved until you approve it.",
        }
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }


def _chat_draft(call: int) -> dict[str, object]:
    if call == 1:
        payload: dict[str, object] = {
            "thought": "Draft the SMA and wait.",
            "action": "create_strategy_draft",
            "action_input": {"template": "sma_cross", "ticker": "AAPL"},
            "final": None,
        }
    else:
        payload = {
            "thought": "Answer from the observations.",
            "action": None,
            "action_input": {},
            "final": "Draft is ready for your approval. Nothing is saved until you approve it.",
        }
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }


def _anthropic_transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_draft_json(len(seen)))

    return httpx.MockTransport(handler), seen


def _spec() -> dict[str, object]:
    spec = StrategySpec.model_validate(
        {
            "name": "cross",
            "universe": ["AAPL"],
            "sizing": {"buffer_pct": 0.01},
            "rules": [
                {
                    "when": {
                        "kind": "compare",
                        "left": {"kind": "indicator", "name": "price", "ticker": "AAPL"},
                        "op": "crosses_above",
                        "right": {"kind": "const", "value": 10},
                    },
                    "then": {
                        "kind": "buy",
                        "ticker": "AAPL",
                        "amount": {"kind": "pct_cash", "value": 100},
                    },
                }
            ],
        }
    )
    return spec.model_dump()


def test_backtest_job_runs_once() -> None:
    client = _client()
    created = client.post("/strategies", json={"dsl": _spec()})
    assert created.status_code == 200
    strategy_id = created.json()["id"]
    queued = client.post("/backtests", json={"strategy_id": strategy_id})
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    backtest_id = queued.json()["id"]
    assert client.post("/jobs/run-once").json() == {"ran": 1}
    done = client.get(f"/backtests/{backtest_id}")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "succeeded"
    assert body["data_label"] == "SYNTHETIC DATA"
    assert body["trades"] == [{"date": "2024-01-03", "side": "BUY", "quantity": 9000.0, "price": 10.005}]
    assert body["metrics"]["ending_equity"] == 99955.0
    assert client.post("/jobs/run-once").json() == {"ran": 0}
    again = client.get(f"/backtests/{backtest_id}").json()
    assert again["trades"] == body["trades"]
    assert again["metrics"]["ending_equity"] == 99955.0


def test_backtest_prefers_a_local_cache_and_labels_real_data(tmp_path: Path) -> None:
    row = (
        "date,open,high,low,close,volume\n"
        "2024-01-02,9,9,9,9,1000\n"
        "2024-01-03,10,11,10,11,1000\n"
        "2024-01-04,11,11,11,11,1000\n"
    )
    (tmp_path / "AAPL.csv").write_text(row, encoding="utf-8")
    (tmp_path / "SPY.csv").write_text(row, encoding="utf-8")
    state = AppState(
        ":memory:",
        PreferLocalMarketData(tmp_path, FixtureMarketData()),
        kek=b"k" * 32,
        http=httpx.Client(transport=httpx.MockTransport(_fail)),
    )
    client = TestClient(create_app(state))
    registered = client.post("/auth/register", json={"email": "real@example.com", "password": "real-password-1"})
    client.headers["Authorization"] = f"Bearer {registered.json()['token']}"
    created = client.post("/strategies", json={"dsl": _spec()})
    queued = client.post("/backtests", json={"strategy_id": created.json()["id"]})
    assert queued.json()["data_label"] == "REAL DATA"
    assert client.post("/jobs/run-once").json() == {"ran": 1}
    body = client.get(f"/backtests/{queued.json()['id']}").json()
    assert body["data_label"] == "REAL DATA"
    assert body["trades"] == [{"date": "2024-01-04", "side": "BUY", "quantity": 9000.0, "price": 11.0055}]
    (tmp_path / "SPY.csv").unlink()
    mixed = client.post("/backtests", json={"strategy_id": created.json()["id"]})
    assert mixed.json()["data_label"] == "SYNTHETIC DATA"


def test_user_isolation() -> None:
    app = create_app(_state())
    alice = TestClient(app)
    bob = TestClient(app)
    alice_token = alice.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "alice-password-1"},
    ).json()["token"]
    bob_token = bob.post(
        "/auth/register",
        json={"email": "bob@example.com", "password": "bob-password-1"},
    ).json()["token"]
    alice.headers["Authorization"] = f"Bearer {alice_token}"
    bob.headers["Authorization"] = f"Bearer {bob_token}"
    created = alice.post("/strategies", json={"dsl": _spec()})
    assert created.status_code == 200
    assert bob.get("/strategies").json() == []
    missing = bob.get(f"/backtests/{created.json()['id']}")
    assert missing.status_code == 404
    anon = TestClient(app)
    assert anon.get("/paper").status_code == 401


def test_paper_eval_is_idempotent() -> None:
    client = _client()
    strategy_id = client.post("/strategies", json={"dsl": _spec()}).json()["id"]
    deployed = client.post(
        "/paper/deploy",
        json={"strategy_id": strategy_id, "started_on": "2024-01-01"},
    )
    assert deployed.status_code == 200
    first = client.post("/paper/eval", json={"as_of": "2024-01-03"})
    assert first.json() == {"inserted": 1}
    account = client.get("/paper").json()
    assert account["orders"] == [{"date": "2024-01-03", "side": "BUY", "quantity": 9000.0, "price": 10.005}]
    assert account["cash"] == 9955.0
    assert account["positions"][0]["quantity"] == 9000.0
    assert account["positions"][0]["last_price"] == 10.0
    assert account["positions"][0]["market_value"] == 90000.0
    assert account["equity"] == 99955.0
    second = client.post("/paper/eval", json={"as_of": "2024-01-03"})
    assert second.json() == {"inserted": 0}
    assert client.get("/paper").json()["orders"] == account["orders"]
    assert client.get("/paper").json()["cash"] == 9955.0


def test_unapproved_proposal_does_not_write_a_strategy() -> None:
    transport, seen = _anthropic_transport()
    client = _client(transport)
    saved = client.put(
        "/settings/keys/anthropic",
        json={"key": "sk-" + "ant-demo-local-key"},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "kind": "anthropic",
        "last4": "-key",
        "status": "valid",
        "validated_at": saved.json()["validated_at"],
    }
    assert ("sk-" + "ant-demo-local-key") not in saved.text
    before = client.get("/strategies").json()
    chat = client.post("/assistant/chat", json={"text": "Build an sma cross"})
    assert chat.status_code == 200
    assert chat.json()["proposal"]["status"] == "pending"
    assert chat.json()["proposal"]["payload"] == {"template": "sma_cross", "ticker": "AAPL"}
    assert client.get("/strategies").json() == before
    assert str(seen[0].url) == "https://api.anthropic.com/v1/messages"
    assert seen[0].headers["x-api-key"] == "sk-" + "ant-demo-local-key"


def test_secret_status_schema_has_no_secret_field() -> None:
    schema = SecretStatus.model_json_schema()
    names = set(schema["properties"])
    assert names == {"kind", "last4", "status", "validated_at"}


def test_approve_creates_the_strategy() -> None:
    transport, _seen = _anthropic_transport()
    client = _client(transport)
    client.put("/settings/keys/anthropic", json={"key": "sk-" + "ant-demo-local-key"})
    chat = client.post("/assistant/chat", json={"text": "Build an sma cross"}).json()
    approved = client.post(f"/assistant/proposals/{chat['proposal']['id']}/approve")
    assert approved.status_code == 200
    names = [row["name"] for row in client.get("/strategies").json()]
    assert names == ["sma_cross"]


def test_no_key_uses_the_scripted_model_and_still_waits_for_approval() -> None:
    client = _client()
    assert client.get("/assistant/status").json() == {
        "enabled": True,
        "provider": "scripted",
        "model": "",
        "options": [],
    }
    before = client.get("/strategies").json()
    chat = client.post("/assistant/chat", json={"text": "Build an sma cross"})
    assert chat.status_code == 200
    assert chat.json()["proposal"]["payload"] == {"template": "sma_cross", "ticker": "AAPL"}
    assert client.get("/strategies").json() == before


def test_sync_portfolio_is_read_only_and_scoped() -> None:
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
                        {"instrument": {"symbol": "AAPL"}, "quantity": 2, "currentValue": 500.0},
                    ],
                },
            )
        raise AssertionError(request.url.path)

    app = create_app(_state(httpx.MockTransport(handler)))
    alice = TestClient(app)
    bob = TestClient(app)
    alice.headers["Authorization"] = (
        "Bearer "
        + alice.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": "alice-password-1"},
        ).json()["token"]
    )
    bob.headers["Authorization"] = (
        "Bearer "
        + bob.post(
            "/auth/register",
            json={"email": "bob@example.com", "password": "bob-password-1"},
        ).json()["token"]
    )
    missing = alice.post("/broker/sync")
    assert missing.status_code == 422
    saved = alice.put("/settings/keys/public_com", json={"key": "pub-" + "readonlydemo1"})
    assert saved.status_code == 200
    synced = alice.post("/broker/sync")
    assert synced.status_code == 200
    body = synced.json()
    assert body["label"] == "REAL ACCOUNT · read-only"
    assert body["account_id"] == "acc-1"
    assert body["equity"] == 1200.5
    assert body["cash"] == 40.0
    assert body["positions"] == [{"symbol": "AAPL", "quantity": 2.0, "market_value": 500.0}]
    assert alice.get("/broker/snapshot").json()["positions"] == body["positions"]
    assert bob.get("/broker/snapshot").json() is None
    assert calls == [
        "/userapiauthservice/personal/access-tokens",
        "/userapigateway/trading/account",
        "/userapigateway/trading/acc-1/portfolio/v2",
    ]
    assert all("order" not in path for path in calls)


def test_openai_and_nous_keys_are_masked_and_the_choice_picks_the_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_chat_draft(len(seen)))

    client = _client(httpx.MockTransport(handler))
    openai_key = "sk-" + "proj-openai-demo-key"
    nous_key = "sk-" + "nous-portal-keyzz"
    assert client.put("/settings/keys/openai", json={"key": "sk-short"}).status_code == 422
    saved_openai = client.put("/settings/keys/openai", json={"key": openai_key})
    assert saved_openai.status_code == 200
    assert saved_openai.json()["kind"] == "openai"
    assert saved_openai.json()["last4"] == "-key"
    assert openai_key not in saved_openai.text
    saved_nous = client.put("/settings/keys/nous", json={"key": nous_key})
    assert saved_nous.status_code == 200
    assert saved_nous.json()["last4"] == "eyzz"
    assert nous_key not in saved_nous.text
    choice = client.put("/assistant/choice", json={"provider": "nous", "model": "Hermes-4.3-36B"})
    assert choice.status_code == 200
    assert choice.json()["provider"] == "nous"
    assert choice.json()["model"] == "Hermes-4.3-36B"
    assert choice.json()["options"] == ["openai", "nous"]
    before = client.get("/strategies").json()
    chat = client.post("/assistant/chat", json={"text": "Build an sma cross"})
    assert chat.status_code == 200
    assert chat.json()["proposal"]["payload"] == {"template": "sma_cross", "ticker": "AAPL"}
    assert client.get("/strategies").json() == before
    assert str(seen[0].url) == "https://inference-api.nousresearch.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer " + nous_key
    body = json.loads(seen[0].content)
    assert body["model"] == "Hermes-4.3-36B"


def test_openai_choice_posts_chat_completions() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_chat_draft(len(seen)))

    client = _client(httpx.MockTransport(handler))
    key = "sk-" + "proj-openai-demo-key"
    client.put("/settings/keys/anthropic", json={"key": "sk-" + "ant-demo-local-key"})
    client.put("/settings/keys/openai", json={"key": key})
    chosen = client.put("/assistant/choice", json={"provider": "openai", "model": "gpt-4o-mini"})
    assert chosen.json()["options"] == ["anthropic", "openai"]
    chat = client.post("/assistant/chat", json={"text": "Build an sma cross"})
    assert chat.status_code == 200
    assert chat.json()["proposal"]["status"] == "pending"
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer " + key
    assert json.loads(seen[0].content)["model"] == "gpt-4o-mini"


def test_dev_uses_the_public_kek_and_warns(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("SAMAR_ENV", raising=False)
    monkeypatch.delenv("SAMAR_KEK", raising=False)
    state = AppState.open(":memory:")
    assert state.kek == resolve_kek("", "dev")
    assert "public development key" in capsys.readouterr().err


def test_production_refuses_a_missing_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMAR_ENV", "production")
    monkeypatch.delenv("SAMAR_KEK", raising=False)
    with pytest.raises(RuntimeError, match="SAMAR_KEK is required"):
        AppState.open(":memory:")


def test_production_refuses_the_development_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMAR_ENV", "production")
    monkeypatch.setenv("SAMAR_KEK", resolve_kek("", "dev").hex())
    with pytest.raises(RuntimeError, match="development SAMAR_KEK is refused"):
        AppState.open(":memory:")


def test_production_accepts_a_64_hex_kek(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SAMAR_ENV", "production")
    monkeypatch.setenv("SAMAR_KEK", "ab" * 32)
    state = AppState.open(":memory:")
    assert state.kek == bytes.fromhex("ab" * 32)
    assert capsys.readouterr().err == ""


def test_arena_ranks_held_out_deflated_sharpe_and_is_idempotent() -> None:
    seen: list[httpx.Request] = []
    sma_fast = random_specs(2)[1]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) != 2:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        payload = {
            "thought": "Try the faster cross.",
            "action": None,
            "action_input": {},
            "final": sma_fast.model_dump_json(),
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 6},
            },
        )

    state = AppState(
        ":memory:",
        FixtureMarketData(),
        kek=b"k" * 32,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(create_app(state))
    registered = client.post("/auth/register", json={"email": "arena@example.com", "password": "arena-password-1"})
    client.headers["Authorization"] = f"Bearer {registered.json()['token']}"
    missing = client.post(
        "/arena/runs",
        json={"contestants": [{"provider": "openai", "model": "gpt-4o-mini"}], "budget_proposals": 2, "token_cap": 100},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"] == "save a openai key first"
    client.put("/settings/keys/openai", json={"key": "sk-" + "proj-openai-demo-key"})
    created = client.post(
        "/arena/runs",
        json={
            "contestants": [
                {"provider": "random", "model": "random-search"},
                {"provider": "openai", "model": "gpt-4o-mini"},
            ],
            "budget_proposals": 3,
            "token_cap": 100,
        },
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["status"] == "queued"
    assert client.post("/jobs/run-once").json() == {"ran": 1}
    assert client.post("/jobs/run-once").json() == {"ran": 0}
    again = client.post(
        "/arena/runs",
        json={
            "contestants": [
                {"provider": "openai", "model": "gpt-4o-mini"},
                {"provider": "random", "model": "random-search"},
            ],
            "budget_proposals": 3,
            "token_cap": 100,
        },
    )
    assert again.json()["id"] == run_id
    view = client.get(f"/arena/runs/{run_id}").json()
    assert view["data_label"] == "SYNTHETIC DATA"
    assert view["ticker"] == "AAPL"
    assert [(row["contestant"], row["model"]) for row in view["entries"]] == [
        ("openai", "gpt-4o-mini"),
        ("baseline", "sma_20_50"),
        ("random", "random-search"),
        ("baseline", "buy_and_hold"),
    ]
    assert [row["rank"] for row in view["entries"]] == [1, 2, 3, 4]
    assert view["entries"][0]["deflated_sharpe"] == pytest.approx(-0.06634746529320527)
    assert view["entries"][0]["test_sharpe"] == pytest.approx(-0.0014065242995221579)
    assert view["entries"][0]["test_sharpe_se"] == pytest.approx(0.0438108171016673)
    assert view["entries"][0]["test_max_drawdown_pct"] == pytest.approx(19.627544429609667)
    assert view["entries"][0]["turnover"] == 9
    assert view["entries"][0]["fold_sharpes"] == pytest.approx([0.7249192938613018, -0.5623460417286588])
    assert view["entries"][0]["n_trials"] == 3
    assert view["entries"][0]["n_failures"] == 2
    assert view["entries"][0]["tokens_in"] == 4
    assert view["entries"][0]["tokens_out"] == 6
    assert view["entries"][1]["deflated_sharpe"] == pytest.approx(-0.0981690441684318)
    assert view["entries"][1]["turnover"] == 4
    assert view["entries"][2]["deflated_sharpe"] == pytest.approx(-0.16326622651831296)
    assert view["entries"][2]["test_sharpe"] == pytest.approx(-0.0981690441684318)
    assert view["entries"][2]["turnover"] == 4
    assert view["entries"][2]["fold_sharpes"] == pytest.approx([1.0171708001046442, -0.927011493162725])
    openai = view["entries"][0]
    assert openai["proposals"][0]["ok"] is False
    assert openai["proposals"][1]["spec_name"] == "sma_cross"
    assert openai["proposals"][1]["train_sharpe"] == pytest.approx(-1.145481, abs=1e-5)
    assert "Historical backtest on a small sample. Not a prediction." in openai["skepticism"]["warnings"]
    assert client.get("/strategies").json() == []
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    assert b"Propose one AAPL strategy" in seen[0].content
    assert b"Do not tell the person what to buy or sell." in seen[0].content
    assert arena_prompt("AAPL", view["train_start"], view["train_end"]).encode() in seen[0].content
    assert b"2024-12-31" not in seen[0].content
    assert b"train sharpe=" in seen[2].content
    assert b"2024-12-31" not in seen[2].content


def test_arena_ticker_must_be_in_the_ten_name_universe() -> None:
    state = AppState(":memory:", FixtureMarketData(), kek=b"k" * 32, http=httpx.Client())
    client = TestClient(create_app(state))
    registered = client.post("/auth/register", json={"email": "tick@example.com", "password": "tick-password-1"})
    client.headers["Authorization"] = f"Bearer {registered.json()['token']}"
    body = {
        "contestants": [{"provider": "random", "model": "random-search"}],
        "budget_proposals": 1,
        "token_cap": 100,
    }
    rejected = client.post("/arena/runs", json={**body, "ticker": "ZZZZ"})
    assert rejected.status_code == 422
    missing = client.post("/arena/runs", json={**body, "ticker": "MSFT"})
    assert missing.status_code == 422
    assert "samar_data.fetch" in missing.json()["detail"]
    accepted = client.post("/arena/runs", json={**body, "ticker": "SPY"})
    assert accepted.status_code == 200
    assert accepted.json()["ticker"] == "SPY"
    assert accepted.json()["data_label"] == "SYNTHETIC DATA"


def test_supabase_bearer_isolates_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMAR_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SAMAR_SUPABASE_ANON_KEY", "anon-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "anon-test-key"
        token = request.headers["authorization"]
        if token.endswith("alice-token-value"):
            return httpx.Response(200, json={"id": "user-alice", "email": "alice@example.com"})
        if token.endswith("bob-token-value"):
            return httpx.Response(200, json={"id": "user-bob", "email": "bob@example.com"})
        return httpx.Response(401, json={"error": "bad"})

    app = create_app(_state(httpx.MockTransport(handler)))
    alice = TestClient(app)
    bob = TestClient(app)
    alice.headers["Authorization"] = "Bearer alice-token-value"
    bob.headers["Authorization"] = "Bearer bob-token-value"
    assert alice.get("/auth/me").json() == {"user_id": "user-alice", "email": "alice@example.com"}
    created = alice.post("/strategies", json={"dsl": _spec()})
    assert created.status_code == 200
    assert bob.get("/strategies").json() == []
    assert bob.get(f"/backtests/{created.json()['id']}").status_code == 404
    assert TestClient(app).get("/paper").status_code == 401

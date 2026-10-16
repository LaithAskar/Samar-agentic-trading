from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr
from samar_contracts.models import SecretStatus
from samar_engine.dsl import StrategySpec

from samar_api.auth import supabase_configured
from samar_api.live.book import LiveBook
from samar_api.live.types import Limits, OrderIntent, SourceChoice
from samar_api.service import AppState

_SHAPES: dict[str, re.Pattern[str]] = {
    "anthropic": re.compile(r"^sk-ant-[A-Za-z0-9_\-]{12,}$"),
    "openrouter": re.compile(r"^sk-or-[A-Za-z0-9_\-]{12,}$"),
    "openai": re.compile(r"^sk-[A-Za-z0-9_\-]{20,}$"),
    "nous": re.compile(r"^sk-nous-[A-Za-z0-9_\-]{8,}$"),
    "public_com": re.compile(r"^pub-[A-Za-z0-9]{12,}$"),
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9_.:/\-]{1,80}$")


class CreateStrategyBody(BaseModel):
    dsl: StrategySpec


class BacktestBody(BaseModel):
    strategy_id: str


class DeployBody(BaseModel):
    strategy_id: str
    started_on: str


class EvalBody(BaseModel):
    as_of: str


class KeyBody(BaseModel):
    key: SecretStr


class ChatBody(BaseModel):
    text: str


class AuthBody(BaseModel):
    email: str
    password: SecretStr


class ChoiceBody(BaseModel):
    provider: str
    model: str


class ArenaContestantBody(BaseModel):
    provider: str
    model: str = ""


class ArenaBody(BaseModel):
    contestants: list[ArenaContestantBody]
    budget_proposals: int = 4
    token_cap: int = 8000


class PhraseBody(BaseModel):
    phrase: str


class LimitsBody(BaseModel):
    capital_cap: float = 200
    max_order_dollars: float = 200
    max_orders_per_day: int | None = 4
    max_orders_per_minute: int = 2
    daily_loss_stop: float = 50


class SourceBody(BaseModel):
    source: str
    strategy_id: str = ""
    provider: str = ""
    model: str = ""


class TicketBody(BaseModel):
    symbol: str
    side: str
    quantity: int
    limit_price: float
    reason: str
    model: str = "manual"


def validate_key(kind: str, key: str) -> bool:
    shape = _SHAPES.get(kind)
    return shape is not None and shape.match(key) is not None


def create_app(state: AppState | None = None) -> FastAPI:
    app = FastAPI(title="Samar API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.samar = state or AppState.open(os.environ.get("SAMAR_DB", "data/samar.db"))

    def samar() -> AppState:
        loaded = app.state.samar
        if not isinstance(loaded, AppState):
            raise RuntimeError("app state missing")
        return loaded

    def require_user(authorization: str | None = Header(default=None)) -> str:
        try:
            return samar().user_from_authorization(authorization).id
        except KeyError as exc:
            raise HTTPException(401, "sign in") from exc

    def _auth_payload(body: AuthBody) -> tuple[str, str]:
        email = body.email.strip().lower()
        password = body.password.get_secret_value()
        if _EMAIL.match(email) is None:
            raise HTTPException(422, "email is invalid")
        if len(password) < 10:
            raise HTTPException(422, "password must be at least 10 characters")
        return email, password

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/auth/config")
    def auth_config() -> dict[str, str]:
        if not supabase_configured():
            return {"mode": "local"}
        return {
            "mode": "supabase",
            "url": os.environ["SAMAR_SUPABASE_URL"].rstrip("/"),
            "anon_key": os.environ["SAMAR_SUPABASE_ANON_KEY"],
        }

    @app.post("/auth/register")
    def register(body: AuthBody) -> dict[str, str]:
        email, password = _auth_payload(body)
        try:
            user, token = samar().register_user(email, password)
        except PermissionError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"token": token, "user_id": user.id, "email": user.email}

    @app.post("/auth/login")
    def login(body: AuthBody) -> dict[str, str]:
        email, password = _auth_payload(body)
        try:
            user, token = samar().login_user(email, password)
        except PermissionError as exc:
            raise HTTPException(400, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(401, "email or password is wrong") from exc
        return {"token": token, "user_id": user.id, "email": user.email}

    @app.post("/auth/logout")
    def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
        samar().logout(authorization)
        return {"status": "signed out"}

    @app.get("/auth/me")
    def me(authorization: str | None = Header(default=None)) -> dict[str, str]:
        try:
            user = samar().user_from_authorization(authorization)
        except KeyError as exc:
            raise HTTPException(401, "sign in") from exc
        return {"user_id": user.id, "email": user.email}

    @app.get("/strategies/templates")
    def templates(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
        require_user(authorization)
        return [view.model_dump() for view in samar().templates()]

    @app.get("/strategies")
    def list_strategies(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
        return [view.model_dump() for view in samar().list_strategies(require_user(authorization))]

    @app.post("/strategies")
    def create_strategy(
        body: CreateStrategyBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        return samar().create_strategy(require_user(authorization), body.dsl).model_dump()

    @app.post("/backtests")
    def create_backtest(body: BacktestBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            view = samar().enqueue_backtest(require_user(authorization), body.strategy_id, "2020-01-01", "2024-12-31")
        except KeyError as exc:
            raise HTTPException(404, "strategy not found") from exc
        return view.model_dump()

    @app.get("/backtests/{backtest_id}")
    def get_backtest(backtest_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            return samar().get_backtest(require_user(authorization), backtest_id).model_dump()
        except KeyError as exc:
            raise HTTPException(404, "backtest not found") from exc

    @app.get("/backtests")
    def list_backtests(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
        return [view.model_dump() for view in samar().list_backtests(require_user(authorization))]

    @app.post("/arena/runs")
    def create_arena(body: ArenaBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        contestants: list[tuple[str, str]] = []
        for item in body.contestants:
            if item.provider != "random" and item.model and _MODEL_ID.match(item.model) is None:
                raise HTTPException(422, "model id is invalid")
            contestants.append((item.provider, item.model))
        try:
            view = samar().enqueue_arena(
                require_user(authorization),
                contestants,
                body.budget_proposals,
                body.token_cap,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.get("/arena/runs/{run_id}")
    def get_arena(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            return samar().get_arena(require_user(authorization), run_id).model_dump()
        except KeyError as exc:
            raise HTTPException(404, "arena run not found") from exc

    @app.post("/jobs/run-once")
    def run_once() -> dict[str, int]:
        return {"ran": samar().run_once()}

    @app.post("/paper/deploy")
    def deploy(body: DeployBody, authorization: str | None = Header(default=None)) -> dict[str, str]:
        try:
            deployment_id = samar().deploy(require_user(authorization), body.strategy_id, body.started_on)
        except KeyError as exc:
            raise HTTPException(404, "strategy not found") from exc
        return {"deployment_id": deployment_id}

    @app.post("/paper/eval")
    def eval_paper(body: EvalBody, authorization: str | None = Header(default=None)) -> dict[str, int]:
        return {"inserted": samar().eval_paper(require_user(authorization), body.as_of)}

    @app.get("/paper")
    def paper(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return samar().paper_account(require_user(authorization)).model_dump()

    @app.get("/settings/keys")
    def list_keys(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
        return [item.model_dump() for item in samar().list_keys(require_user(authorization))]

    @app.put("/settings/keys/{kind}")
    def put_key(kind: str, body: KeyBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        plaintext = body.key.get_secret_value()
        if not validate_key(kind, plaintext):
            raise HTTPException(422, "key failed validation")
        status: SecretStatus = samar().save_key(require_user(authorization), kind, plaintext, True)
        return status.model_dump()

    @app.delete("/settings/keys/{kind}")
    def delete_key(kind: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
        samar().delete_key(require_user(authorization), kind)
        return {"status": "revoked"}

    @app.get("/assistant/status")
    def assistant_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return samar().assistant_status(require_user(authorization))

    @app.put("/assistant/choice")
    def assistant_choice(body: ChoiceBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        if _MODEL_ID.match(body.model) is None:
            raise HTTPException(422, "model id is invalid")
        try:
            samar().set_assistant_choice(require_user(authorization), body.provider, body.model)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return samar().assistant_status(require_user(authorization))

    @app.post("/assistant/chat")
    def chat(body: ChatBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            events, proposal = samar().chat(require_user(authorization), body.text)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            raise HTTPException(502, "model call failed") from exc
        return {"events": events, "proposal": None if proposal is None else proposal.model_dump()}

    @app.post("/assistant/chat/stream")
    def chat_stream(body: ChatBody, authorization: str | None = Header(default=None)) -> StreamingResponse:
        user_id = require_user(authorization)
        try:
            events, proposal = samar().chat(user_id, body.text)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            raise HTTPException(502, "model call failed") from exc

        def gen() -> Iterator[str]:
            for event in events:
                yield f"event: {event['kind']}\ndata: {event['text']}\n\n"
            if proposal is not None:
                yield f"event: proposal\ndata: {proposal.model_dump_json()}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/assistant/proposals/{proposal_id}/approve")
    def approve(proposal_id: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
        try:
            result_id = samar().approve(require_user(authorization), proposal_id)
        except KeyError as exc:
            raise HTTPException(404, "proposal not found") from exc
        return {"id": result_id}

    @app.post("/broker/sync")
    def broker_sync(authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            view = samar().sync_public(require_user(authorization))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Public.com read failed") from exc
        return view.model_dump()

    @app.get("/broker/snapshot")
    def broker_snapshot(authorization: str | None = Header(default=None)) -> dict[str, object] | None:
        view = samar().broker_snapshot(require_user(authorization))
        return None if view is None else view.model_dump()

    def live_book() -> LiveBook:
        state = samar()
        return LiveBook(state.conn, state.http, state.read_key, state.market)

    @app.get("/live/status")
    def live_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return live_book().status(require_user(authorization)).model_dump()

    @app.get("/live/audit")
    def live_audit(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
        rows = live_book().audit(require_user(authorization))
        return [row.model_dump() for row in rows]

    @app.post("/live/enable")
    def live_enable(body: PhraseBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            view = live_book().enable(require_user(authorization), body.phrase, datetime.now(UTC))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.post("/live/auto")
    def live_auto(body: PhraseBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            view = live_book().enable_auto(require_user(authorization), body.phrase, datetime.now(UTC))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.post("/live/manual")
    def live_manual(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return live_book().manual(require_user(authorization), datetime.now(UTC)).model_dump()

    @app.post("/live/disable")
    def live_disable(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return live_book().disable(require_user(authorization), datetime.now(UTC)).model_dump()

    @app.post("/live/kill")
    def live_kill(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return live_book().kill(require_user(authorization), datetime.now(UTC)).model_dump()

    @app.put("/live/limits")
    def live_limits(body: LimitsBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            view = live_book().set_limits(
                require_user(authorization),
                Limits(
                    capital_cap=body.capital_cap,
                    max_order_dollars=body.max_order_dollars,
                    max_orders_per_day=body.max_orders_per_day,
                    max_orders_per_minute=body.max_orders_per_minute,
                    daily_loss_stop=body.daily_loss_stop,
                ),
                datetime.now(UTC),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.put("/live/source")
    def live_source(body: SourceBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        if body.source not in {"off", "strategy", "model"}:
            raise HTTPException(422, "source must be off, strategy, or model")
        try:
            view = live_book().set_source(
                require_user(authorization),
                SourceChoice(
                    source="strategy" if body.source == "strategy" else "model" if body.source == "model" else "off",
                    strategy_id=body.strategy_id,
                    provider=body.provider,
                    model=body.model,
                ),
                datetime.now(UTC),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.post("/live/tickets")
    def live_ticket(body: TicketBody, authorization: str | None = Header(default=None)) -> dict[str, object]:
        if body.side not in {"BUY", "SELL"}:
            raise HTTPException(422, "side must be BUY or SELL")
        try:
            view = live_book().propose(
                require_user(authorization),
                OrderIntent(
                    symbol=body.symbol,
                    side="BUY" if body.side == "BUY" else "SELL",
                    quantity=body.quantity,
                    limit_price=body.limit_price,
                    reason=body.reason,
                    model=body.model,
                ),
                datetime.now(UTC),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.post("/live/tickets/{ticket_id}/approve")
    def live_approve(ticket_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            view = live_book().approve(require_user(authorization), ticket_id, datetime.now(UTC))
        except KeyError as exc:
            raise HTTPException(404, "ticket not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return view.model_dump()

    @app.post("/live/check")
    def live_check(authorization: str | None = Header(default=None)) -> dict[str, int]:
        user_id = require_user(authorization)
        placed = live_book().run_cycle(user_id, datetime.now(UTC), None)
        return {"placed": placed}

    return app

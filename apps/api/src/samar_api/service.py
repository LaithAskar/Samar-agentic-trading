from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import UTC, date, datetime
from typing import Literal

import httpx
from samar_agent.advice import scrub_advice
from samar_agent.http_model import (
    ANTHROPIC_URL,
    DEFAULT_MODELS,
    NOUS_URL,
    OPENAI_URL,
    OPENROUTER_URL,
    HttpChatModel,
    ProviderName,
)
from samar_agent.loop import Budget, ChatModel, Proposal, ScriptedModel, run_turn
from samar_brokers.public_readonly import AUTH_URL, GATEWAY, PublicReadOnly
from samar_contracts.models import (
    ArenaRunView,
    BacktestView,
    BrokerPositionView,
    BrokerSnapshotView,
    EquityPoint,
    MetricsView,
    PaperAccountView,
    PaperPositionView,
    ProposalView,
    SecretStatus,
    SkepticismView,
    StrategyView,
    TradeView,
)
from samar_data.market import FixtureMarketData, MarketData
from samar_engine.backtest.engine import BacktestEngine
from samar_engine.backtest.metrics import compute_metrics, daily_returns
from samar_engine.backtest.rigor import buy_and_hold, sharpe_significance
from samar_engine.core.events import Bar
from samar_engine.dsl import (
    StrategySpec,
    compile_strategy,
    rsi_mean_rev_spec,
    sma_cross_spec,
)
from samar_engine.skepticism import build_skepticism
from samar_secrets.vault import SealedSecret, associated_data, open_secret, rewrap, seal

from samar_api.arena_run import arena_view, execute_arena
from samar_api.auth import (
    SessionUser,
    hash_password,
    new_salt,
    new_token,
    password_matches,
    supabase_configured,
    token_hash,
)
from samar_api.store import connect, rows_for_user

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
_MODEL_ORDER: tuple[ProviderName, ...] = ("anthropic", "openrouter", "openai", "nous")


class _HttpSpec:
    def __init__(self, name: ProviderName, url: str, env: str) -> None:
        self.name = name
        self.url = url
        self.env = env


_PROVIDER_HTTP: dict[str, _HttpSpec] = {
    "anthropic": _HttpSpec("anthropic", ANTHROPIC_URL, "SAMAR_ANTHROPIC_URL"),
    "openrouter": _HttpSpec("openrouter", OPENROUTER_URL, "SAMAR_OPENROUTER_URL"),
    "openai": _HttpSpec("openai", OPENAI_URL, "SAMAR_OPENAI_URL"),
    "nous": _HttpSpec("nous", NOUS_URL, "SAMAR_NOUS_URL"),
}
_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


def transition(current: str, nxt: str) -> str:
    if nxt not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal job transition {current} -> {nxt}")
    return nxt


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _json_field(text: str, name: str) -> object:
    parsed: object = json.loads(text)
    if not isinstance(parsed, dict):
        return None
    for key, value in parsed.items():
        if key == name:
            return value
    return None


def _provider_name(value: str) -> ProviderName | None:
    if value == "anthropic":
        return "anthropic"
    if value == "openrouter":
        return "openrouter"
    if value == "openai":
        return "openai"
    if value == "nous":
        return "nous"
    return None


def _bearer(authorization: str | None) -> str | None:
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


_DEV_KEK = b"dev-kek-not-for-prod-use!!!!"[:32].ljust(32, b"!")
_DEV_ENVS = frozenset({"", "dev", "development", "local", "test"})


def resolve_kek(raw: str, env_name: str) -> bytes:
    dev = env_name.strip().lower() in _DEV_ENVS
    if raw == "":
        if not dev:
            raise RuntimeError("SAMAR_KEK is required when SAMAR_ENV is not a development name")
        print("warning: SAMAR_KEK is unset. This process is using the public development key.", file=sys.stderr)
        return _DEV_KEK
    try:
        kek = bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError("SAMAR_KEK must be 64 hex characters") from exc
    if len(kek) != 32:
        raise RuntimeError("SAMAR_KEK must be 64 hex characters")
    if kek == _DEV_KEK and not dev:
        raise RuntimeError("the development SAMAR_KEK is refused when SAMAR_ENV is not a development name")
    return kek


def _arena_contestants(contestants: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not contestants:
        raise ValueError("pick at least one contestant")
    filled: list[tuple[str, str]] = []
    for provider, model in contestants:
        if provider == "random":
            filled.append(("random", "random-search"))
            continue
        known = _provider_name(provider)
        if known is None:
            raise ValueError("unknown contestant")
        filled.append((known, model or DEFAULT_MODELS[known]))
    return filled


class AppState:
    def __init__(self, db_path: str, market: MarketData, kek: bytes, http: httpx.Client | None = None) -> None:
        self.conn = connect(db_path)
        self.market = market
        self.kek = kek
        self.kek_version = 1
        self.http = http or httpx.Client(timeout=30.0)

    @classmethod
    def open(
        cls,
        db_path: str,
        market: MarketData | None = None,
        kek: bytes | None = None,
        http: httpx.Client | None = None,
    ) -> AppState:
        if kek is None:
            kek = resolve_kek(os.environ.get("SAMAR_KEK", ""), os.environ.get("SAMAR_ENV", ""))
        return cls(db_path, market or FixtureMarketData(), kek, http)

    def templates(self) -> list[StrategyView]:
        specs = [sma_cross_spec("AAPL"), rsi_mean_rev_spec("AAPL")]
        return [
            StrategyView(id=spec.name, name=spec.name, universe=spec.universe, dsl=spec.model_dump()) for spec in specs
        ]

    def create_strategy(self, user_id: str, spec: StrategySpec) -> StrategyView:
        strategy_id = _id("str")
        self.conn.execute(
            "INSERT INTO strategies (id, user_id, name, dsl_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (strategy_id, user_id, spec.name, spec.model_dump_json(), _now()),
        )
        self.conn.commit()
        return StrategyView(
            id=strategy_id,
            name=spec.name,
            universe=list(spec.universe),
            dsl=spec.model_dump(),
        )

    def list_strategies(self, user_id: str) -> list[StrategyView]:
        views: list[StrategyView] = []
        for row in rows_for_user(self.conn, "strategies", user_id):
            spec = StrategySpec.model_validate_json(row["dsl_json"])
            views.append(
                StrategyView(id=row["id"], name=spec.name, universe=list(spec.universe), dsl=spec.model_dump())
            )
        return views

    def _load_spec(self, user_id: str, strategy_id: str) -> StrategySpec:
        row = self.conn.execute(
            "SELECT dsl_json FROM strategies WHERE id = ? AND user_id = ?",
            (strategy_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(strategy_id)
        return StrategySpec.model_validate_json(row["dsl_json"])

    def enqueue_backtest(
        self,
        user_id: str,
        strategy_id: str,
        start: str,
        end: str,
    ) -> BacktestView:
        self._load_spec(user_id, strategy_id)
        backtest_id = _id("bt")
        job_id = _id("job")
        created = _now()
        self.conn.execute(
            """INSERT INTO backtests
            (id, user_id, strategy_id, status, created_at) VALUES (?, ?, ?, 'queued', ?)""",
            (backtest_id, user_id, strategy_id, created),
        )
        self.conn.execute(
            """INSERT INTO jobs (id, user_id, job_key, status, backtest_id, created_at)
            VALUES (?, ?, ?, 'queued', ?, ?)""",
            (job_id, user_id, f"backtest:{backtest_id}", backtest_id, created),
        )
        self.conn.commit()
        return self.get_backtest(user_id, backtest_id)

    def get_backtest(self, user_id: str, backtest_id: str) -> BacktestView:
        row = self.conn.execute(
            "SELECT * FROM backtests WHERE id = ? AND user_id = ?",
            (backtest_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(backtest_id)
        return _backtest_view(row)

    def enqueue_arena(
        self,
        user_id: str,
        contestants: list[tuple[str, str]],
        budget_proposals: int,
        token_cap: int,
    ) -> ArenaRunView:
        ordered = sorted(_arena_contestants(contestants))
        if not 1 <= budget_proposals <= 8:
            raise ValueError("budget must be from 1 to 8")
        if not 1 <= token_cap <= 100_000:
            raise ValueError("token cap must be from 1 to 100000")
        if len(ordered) != len(set(ordered)):
            raise ValueError("duplicate contestant")
        for provider, _model in ordered:
            if provider != "random" and self.read_key(user_id, provider) is None:
                raise ValueError(f"save a {provider} key first")
        parts = [f"{provider}:{model}" for provider, model in ordered]
        fingerprint = f"{budget_proposals}:{token_cap}:" + ",".join(parts)
        job_key = f"arena:{user_id}:{fingerprint}"
        existing = self.conn.execute("SELECT backtest_id, status FROM jobs WHERE job_key = ?", (job_key,)).fetchone()
        if existing is not None:
            return arena_view(self.conn, user_id, str(existing["backtest_id"]))
        run_id = _id("arn")
        created = _now()
        payload = [{"provider": provider, "model": model} for provider, model in ordered]
        self.conn.execute(
            """INSERT INTO arena_runs
            (id, user_id, status, ticker, budget_proposals, token_cap, contestants_json, created_at)
            VALUES (?, ?, 'queued', 'AAPL', ?, ?, ?, ?)""",
            (run_id, user_id, budget_proposals, token_cap, json.dumps(payload), created),
        )
        self.conn.execute(
            """INSERT INTO jobs (id, user_id, job_key, status, backtest_id, created_at)
            VALUES (?, ?, ?, 'queued', ?, ?)""",
            (_id("job"), user_id, job_key, run_id, created),
        )
        self.conn.commit()
        return arena_view(self.conn, user_id, run_id)

    def get_arena(self, user_id: str, run_id: str) -> ArenaRunView:
        return arena_view(self.conn, user_id, run_id)

    def list_backtests(self, user_id: str) -> list[BacktestView]:
        rows = self.conn.execute(
            "SELECT * FROM backtests WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        return [_backtest_view(row) for row in rows]

    def run_once(self) -> int:
        self.conn.execute("BEGIN IMMEDIATE")
        row = self.conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            self.conn.commit()
            return 0
        nxt = transition(row["status"], "running")
        updated = self.conn.execute(
            "UPDATE jobs SET status = ? WHERE id = ? AND status = 'queued'",
            (nxt, row["id"]),
        )
        if updated.rowcount != 1:
            self.conn.commit()
            return 0
        arena = str(row["job_key"]).startswith("arena:")
        if arena:
            self.conn.execute("UPDATE arena_runs SET status = 'running' WHERE id = ?", (row["backtest_id"],))
        else:
            self.conn.execute(
                "UPDATE backtests SET status = 'running' WHERE id = ?",
                (row["backtest_id"],),
            )
        self.conn.commit()
        try:
            if arena:
                execute_arena(self.conn, self.market, self.http, self.read_key, row["user_id"], row["backtest_id"])
            else:
                self._execute_backtest(row["user_id"], row["backtest_id"])
            self._finish_job(row["id"], row["backtest_id"], "succeeded", None, arena)
        except Exception as exc:
            self._finish_job(row["id"], row["backtest_id"], "failed", str(exc), arena)
        return 1

    def _finish_job(
        self,
        job_id: str,
        backtest_id: str,
        status: str,
        error: str | None,
        arena: bool = False,
    ) -> None:
        current = self.conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if current is None:
            return
        nxt = transition(str(current["status"]), status)
        self.conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (nxt, job_id))
        if arena:
            self.conn.execute(
                "UPDATE arena_runs SET status = ?, error = ? WHERE id = ?",
                (nxt, error, backtest_id),
            )
        else:
            self.conn.execute(
                "UPDATE backtests SET status = ?, error = ? WHERE id = ?",
                (nxt, error, backtest_id),
            )
        self.conn.commit()

    def _execute_backtest(self, user_id: str, backtest_id: str) -> None:
        row = self.conn.execute("SELECT * FROM backtests WHERE id = ?", (backtest_id,)).fetchone()
        if row is None:
            raise KeyError(backtest_id)
        spec = self._load_spec(user_id, row["strategy_id"])
        ticker = spec.universe[0]
        bars = self.market.bars(ticker, date(2020, 1, 1), date(2024, 12, 31))
        engine = BacktestEngine(starting_cash=100_000.0, slippage_bps=5.0)
        result = engine.run(compile_strategy(spec), ticker, iter(bars))
        metrics = compute_metrics(result.portfolio)
        bench_bars = self.market.bars("SPY", date(2020, 1, 1), date(2024, 12, 31))
        benchmark = buy_and_hold(bars, starting_cash=100_000.0)
        returns = daily_returns([point[1] for point in result.portfolio.equity_curve])
        _t_stat, p_value = sharpe_significance(returns)
        sample_days = (bars[-1].timestamp - bars[0].timestamp).days if len(bars) >= 2 else 0
        skepticism = build_skepticism(metrics, benchmark, p_value, sample_days)
        equity = [{"date": ts.date().isoformat(), "equity": value} for ts, value in result.portfolio.equity_curve]
        bench_equity = _benchmark_curve(bench_bars or bars, 100_000.0)
        trades = [
            {
                "date": fill.timestamp.date().isoformat(),
                "side": fill.side.value,
                "quantity": fill.quantity,
                "price": fill.price,
            }
            for fill in result.portfolio.fills
        ]
        self.conn.execute(
            """UPDATE backtests SET metrics_json = ?, skepticism_json = ?, equity_json = ?,
            benchmark_json = ?, trades_json = ? WHERE id = ?""",
            (
                json.dumps(metrics.__dict__),
                skepticism.model_dump_json(),
                json.dumps(equity),
                json.dumps(bench_equity),
                json.dumps(trades),
                backtest_id,
            ),
        )
        self.conn.commit()

    def ensure_paper(self, user_id: str, starting_cash: float = 100_000.0) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO paper_cash (user_id, starting_cash) VALUES (?, ?)",
            (user_id, starting_cash),
        )
        self.conn.commit()

    def deploy(self, user_id: str, strategy_id: str, started_on: str) -> str:
        self._load_spec(user_id, strategy_id)
        self.ensure_paper(user_id)
        deployment_id = _id("dep")
        self.conn.execute(
            """INSERT INTO deployments (id, user_id, strategy_id, started_on, active)
            VALUES (?, ?, ?, ?, 1)""",
            (deployment_id, user_id, strategy_id, started_on),
        )
        self.conn.commit()
        return deployment_id

    def eval_paper(self, user_id: str, as_of: str) -> int:
        inserted = 0
        deployments = self.conn.execute(
            "SELECT * FROM deployments WHERE user_id = ? AND active = 1",
            (user_id,),
        ).fetchall()
        for deployment in deployments:
            spec = self._load_spec(user_id, deployment["strategy_id"])
            ticker = spec.universe[0]
            bars = [
                bar
                for bar in self.market.bars(
                    ticker, date.fromisoformat(deployment["started_on"]), date.fromisoformat(as_of)
                )
            ]
            result = BacktestEngine(starting_cash=100_000.0, slippage_bps=5.0).run(
                compile_strategy(spec),
                ticker,
                iter(bars),
            )
            for fill in result.portfolio.fills:
                if fill.timestamp.date().isoformat() < deployment["started_on"]:
                    continue
                if fill.timestamp.date().isoformat() > as_of:
                    continue
                key = f"{deployment['strategy_id']}:{fill.timestamp.date().isoformat()}:{fill.side.value}"
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO paper_orders
                    (id, user_id, strategy_id, eval_key, ticker, side, quantity, price, filled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _id("ord"),
                        user_id,
                        deployment["strategy_id"],
                        key,
                        fill.symbol,
                        fill.side.value,
                        fill.quantity,
                        fill.price,
                        fill.timestamp.date().isoformat(),
                    ),
                )
                inserted += cursor.rowcount
        self.conn.commit()
        return inserted

    def _last_close(self, ticker: str) -> float | None:
        bars = self.market.bars(ticker, date(2020, 1, 1), date(2024, 12, 31))
        if not bars:
            return None
        return bars[-1].close

    def paper_account(self, user_id: str) -> PaperAccountView:
        self.ensure_paper(user_id)
        cash_row = self.conn.execute(
            "SELECT starting_cash FROM paper_cash WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        starting = float(cash_row["starting_cash"]) if cash_row else 100_000.0
        orders = self.conn.execute(
            "SELECT * FROM paper_orders WHERE user_id = ? ORDER BY filled_at",
            (user_id,),
        ).fetchall()
        cash = starting
        lots: dict[str, list[list[float]]] = {}
        last_price: dict[str, float] = {}
        trade_views: list[TradeView] = []
        for order in orders:
            qty = float(order["quantity"])
            price = float(order["price"])
            ticker = str(order["ticker"])
            last_price[ticker] = price
            if order["side"] == "BUY":
                cash -= qty * price
                lots.setdefault(ticker, []).append([qty, price])
            else:
                cash += qty * price
                remaining = qty
                book = lots.setdefault(ticker, [])
                while remaining > 1e-9 and book:
                    take = min(book[0][0], remaining)
                    book[0][0] -= take
                    remaining -= take
                    if book[0][0] <= 1e-9:
                        book.pop(0)
            trade_views.append(
                TradeView(
                    date=order["filled_at"],
                    side=order["side"],
                    quantity=qty,
                    price=price,
                )
            )
        positions: list[PaperPositionView] = []
        market_value = 0.0
        for ticker, book in lots.items():
            quantity = sum(lot[0] for lot in book)
            if quantity <= 1e-9:
                continue
            cost = sum(lot[0] * lot[1] for lot in book)
            avg = cost / quantity
            mark = self._last_close(ticker)
            if mark is None:
                mark = last_price.get(ticker, avg)
            value = quantity * mark
            market_value += value
            positions.append(
                PaperPositionView(
                    ticker=ticker,
                    quantity=quantity,
                    avg_price=avg,
                    last_price=mark,
                    market_value=value,
                )
            )
        equity = cash + market_value
        return PaperAccountView(
            cash=cash,
            equity=equity,
            starting_cash=starting,
            pnl=equity - starting,
            positions=positions,
            orders=trade_views,
        )

    def save_key(self, user_id: str, kind: str, plaintext: str, valid: bool) -> SecretStatus:
        if not valid:
            raise ValueError("key failed validation")
        sealed = seal(plaintext, associated_data(user_id, kind), self.kek, self.kek_version)
        secret_id = _id("sec")
        created = _now()
        self.conn.execute("DELETE FROM user_secrets WHERE user_id = ? AND kind = ?", (user_id, kind))
        self.conn.execute(
            """INSERT INTO user_secrets
            (id, user_id, kind, ciphertext, wrapped_dek, nonce, dek_nonce, kek_version,
             last4, status, validated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid', ?, ?)""",
            (
                secret_id,
                user_id,
                kind,
                sealed.ciphertext,
                sealed.wrapped_dek,
                sealed.nonce,
                sealed.dek_nonce,
                sealed.kek_version,
                sealed.last4,
                created,
                created,
            ),
        )
        self.conn.execute(
            "INSERT INTO audit_log (id, user_id, action, created_at) VALUES (?, ?, ?, ?)",
            (_id("aud"), user_id, f"save:{kind}", created),
        )
        self.conn.commit()
        return SecretStatus.model_validate(
            {
                "kind": kind,
                "last4": sealed.last4,
                "status": "valid",
                "validated_at": created,
            }
        )

    def list_keys(self, user_id: str) -> list[SecretStatus]:
        views: list[SecretStatus] = []
        for row in rows_for_user(self.conn, "user_secrets", user_id):
            views.append(
                SecretStatus(
                    kind=row["kind"],
                    last4=row["last4"],
                    status=row["status"],
                    validated_at=row["validated_at"],
                )
            )
        return views

    def delete_key(self, user_id: str, kind: str) -> None:
        self.conn.execute("DELETE FROM user_secrets WHERE user_id = ? AND kind = ?", (user_id, kind))
        self.conn.execute(
            "INSERT INTO audit_log (id, user_id, action, created_at) VALUES (?, ?, ?, ?)",
            (_id("aud"), user_id, f"revoke:{kind}", _now()),
        )
        self.conn.commit()

    def rotate_kek(self, new_kek: bytes, new_version: int) -> int:
        rows = self.conn.execute("SELECT * FROM user_secrets").fetchall()
        count = 0
        for row in rows:
            sealed = SealedSecret(
                ciphertext=row["ciphertext"],
                wrapped_dek=row["wrapped_dek"],
                nonce=row["nonce"],
                dek_nonce=row["dek_nonce"],
                kek_version=row["kek_version"],
                last4=row["last4"],
            )
            aad = associated_data(row["user_id"], row["kind"])
            rotated = rewrap(sealed, aad, self.kek, new_kek, new_version)
            self.conn.execute(
                """UPDATE user_secrets SET wrapped_dek = ?, dek_nonce = ?, kek_version = ?
                WHERE id = ?""",
                (rotated.wrapped_dek, rotated.dek_nonce, rotated.kek_version, row["id"]),
            )
            count += 1
        self.kek = new_kek
        self.kek_version = new_version
        self.conn.commit()
        return count

    def read_key(self, user_id: str, kind: str) -> str | None:
        row = self.conn.execute(
            "SELECT * FROM user_secrets WHERE user_id = ? AND kind = ? AND status = 'valid'",
            (user_id, kind),
        ).fetchone()
        if row is None:
            return None
        sealed = SealedSecret(
            ciphertext=row["ciphertext"],
            wrapped_dek=row["wrapped_dek"],
            nonce=row["nonce"],
            dek_nonce=row["dek_nonce"],
            kek_version=row["kek_version"],
            last4=row["last4"],
        )
        return open_secret(sealed, associated_data(user_id, kind), self.kek)

    def register_user(self, email: str, password: str) -> tuple[SessionUser, str]:
        if supabase_configured():
            raise PermissionError("local accounts are off")
        existing = self.conn.execute("SELECT id FROM local_users WHERE email = ?", (email,)).fetchone()
        if existing is not None:
            raise ValueError("email taken")
        user = SessionUser(id=_id("usr"), email=email)
        salt = new_salt()
        self.conn.execute(
            """INSERT INTO local_users (id, email, password_hash, salt, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (user.id, user.email, hash_password(password, bytes.fromhex(salt)), salt, _now()),
        )
        token = self._issue_session(user.id)
        self.conn.commit()
        return user, token

    def login_user(self, email: str, password: str) -> tuple[SessionUser, str]:
        if supabase_configured():
            raise PermissionError("local accounts are off")
        row = self.conn.execute("SELECT * FROM local_users WHERE email = ?", (email,)).fetchone()
        if row is None or not password_matches(password, str(row["salt"]), str(row["password_hash"])):
            raise KeyError(email)
        user = SessionUser(id=str(row["id"]), email=str(row["email"]))
        token = self._issue_session(user.id)
        self.conn.commit()
        return user, token

    def _issue_session(self, user_id: str) -> str:
        token = new_token()
        self.conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at) VALUES (?, ?, ?)",
            (token_hash(token), user_id, _now()),
        )
        return token

    def logout(self, authorization: str | None) -> None:
        token = _bearer(authorization)
        if token is None or supabase_configured():
            return
        self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        self.conn.commit()

    def user_from_authorization(self, authorization: str | None) -> SessionUser:
        token = _bearer(authorization)
        if token is None:
            raise KeyError("missing token")
        if supabase_configured():
            return self._supabase_user(token)
        row = self.conn.execute(
            """SELECT local_users.id, local_users.email FROM sessions
            JOIN local_users ON local_users.id = sessions.user_id
            WHERE sessions.token_hash = ?""",
            (token_hash(token),),
        ).fetchone()
        if row is None:
            raise KeyError("missing session")
        return SessionUser(id=str(row["id"]), email=str(row["email"]))

    def _supabase_user(self, token: str) -> SessionUser:
        base = os.environ["SAMAR_SUPABASE_URL"].rstrip("/")
        anon = os.environ["SAMAR_SUPABASE_ANON_KEY"]
        response = self.http.get(
            f"{base}/auth/v1/user",
            headers={"apikey": anon, "Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            raise KeyError("supabase rejected the token")
        user_id = _json_field(response.text, "id")
        email = _json_field(response.text, "email")
        if not isinstance(user_id, str) or not user_id:
            raise KeyError("supabase user id")
        return SessionUser(id=user_id, email=email if isinstance(email, str) else "")

    def assistant_status(self, user_id: str) -> dict[str, object]:
        provider, model = self._selected_model(user_id)
        options = [name for name in _MODEL_ORDER if self.read_key(user_id, name) is not None]
        return {"enabled": True, "provider": provider, "model": model, "options": options}

    def set_assistant_choice(self, user_id: str, provider: str, model: str) -> None:
        if provider not in _MODEL_ORDER:
            raise ValueError("unknown provider")
        if self.read_key(user_id, provider) is None:
            raise ValueError("save that provider key first")
        self.conn.execute(
            """INSERT INTO assistant_choice (user_id, provider, model) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET provider = excluded.provider, model = excluded.model""",
            (user_id, provider, model),
        )
        self.conn.commit()

    def _selected_model(self, user_id: str) -> tuple[ProviderName | Literal["scripted"], str]:
        saved: list[ProviderName] = []
        for name in _MODEL_ORDER:
            if self.read_key(user_id, name) is not None:
                saved.append(name)
        row = self.conn.execute(
            "SELECT provider, model FROM assistant_choice WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is not None:
            chosen = _provider_name(str(row["provider"]))
            if chosen is not None and chosen in saved:
                return chosen, str(row["model"])
        if saved:
            provider = saved[0]
            return provider, DEFAULT_MODELS[provider]
        return "scripted", ""

    def _chat_model(self, user_id: str) -> tuple[ChatModel, str]:
        provider, model = self._selected_model(user_id)
        if provider == "scripted":
            return ScriptedModel(), "claude-haiku-4-5"
        spec = _PROVIDER_HTTP[provider]
        key = self.read_key(user_id, provider)
        if key is None:
            raise PermissionError("assistant disabled until an AI key is saved")
        return HttpChatModel(provider, key, self.http, model, os.environ.get(spec.env, spec.url)), model

    def chat(self, user_id: str, text: str) -> tuple[list[dict[str, str]], ProposalView | None]:
        model, model_name = self._chat_model(user_id)
        spent_row = self.conn.execute(
            "SELECT spent_dollars FROM agent_spend WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        spent = float(spent_row["spent_dollars"]) if spent_row else 0.0
        budget = Budget(limit_dollars=1.0)
        budget.spent = spent

        def tool(name: str, payload: dict[str, str]) -> tuple[str, Proposal | None]:
            if name == "create_strategy_draft":
                proposal = Proposal(proposal_id=_id("pr"), kind="create_strategy", payload=payload)
                self._insert_proposal(user_id, proposal)
                return ("draft stored as a proposal", proposal)
            if name == "run_backtest":
                proposal = Proposal(proposal_id=_id("pr"), kind="run_backtest", payload=payload)
                self._insert_proposal(user_id, proposal)
                return ("backtest stored as a proposal", proposal)
            if name == "list_strategies":
                names = [view.name for view in self.list_strategies(user_id)]
                return ("strategies=" + ",".join(names), None)
            return ("no data", None)

        events = run_turn(scrub_advice(text), model, tool, budget, model_name)
        self.conn.execute(
            """INSERT INTO agent_spend (user_id, spent_dollars) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET spent_dollars = ?""",
            (user_id, budget.spent, budget.spent),
        )
        self.conn.commit()
        public = [{"kind": event.kind, "text": event.text} for event in events]
        proposal = next((event.proposal for event in events if event.proposal is not None), None)
        view = None
        if proposal is not None:
            view = ProposalView(
                id=proposal.proposal_id,
                kind=proposal.kind,
                status="pending",
                payload=proposal.payload,
            )
        return public, view

    def _insert_proposal(self, user_id: str, proposal: Proposal) -> None:
        self.conn.execute(
            """INSERT INTO proposals (id, user_id, kind, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)""",
            (proposal.proposal_id, user_id, proposal.kind, json.dumps(proposal.payload), _now()),
        )
        self.conn.commit()

    def approve(self, user_id: str, proposal_id: str) -> str:
        row = self.conn.execute(
            "SELECT * FROM proposals WHERE id = ? AND user_id = ? AND status = 'pending'",
            (proposal_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        payload = json.loads(row["payload_json"])
        if row["kind"] == "create_strategy":
            template = payload.get("template", "sma_cross")
            ticker = payload.get("ticker", "AAPL")
            spec = sma_cross_spec(ticker) if template == "sma_cross" else rsi_mean_rev_spec(ticker)
            created = self.create_strategy(user_id, spec)
            result_id = created.id
        else:
            strategy_id = payload.get("strategy_id", "")
            if strategy_id in {"", "pending"}:
                strategies = self.list_strategies(user_id)
                if not strategies:
                    raise ValueError("no strategy to backtest")
                strategy_id = strategies[0].id
            created_bt = self.enqueue_backtest(user_id, strategy_id, "2020-01-01", "2024-12-31")
            result_id = created_bt.id
        self.conn.execute(
            "UPDATE proposals SET status = 'approved' WHERE id = ?",
            (proposal_id,),
        )
        self.conn.commit()
        return result_id

    def reject(self, user_id: str, proposal_id: str) -> None:
        self.conn.execute(
            "UPDATE proposals SET status = 'rejected' WHERE id = ? AND user_id = ?",
            (proposal_id, user_id),
        )
        self.conn.commit()

    def sync_public(self, user_id: str) -> BrokerSnapshotView:
        secret = self.read_key(user_id, "public_com")
        if secret is None:
            raise ValueError("save a Public.com key first")
        broker = PublicReadOnly(
            secret,
            self.http,
            auth_url=os.environ.get("SAMAR_PUBLIC_AUTH_URL", AUTH_URL),
            gateway=os.environ.get("SAMAR_PUBLIC_GATEWAY", GATEWAY),
        )
        return self.sync_broker(user_id, broker)

    def sync_broker(self, user_id: str, broker: PublicReadOnly) -> BrokerSnapshotView:
        accounts = broker.list_accounts()
        if not accounts:
            raise ValueError("Public returned no accounts")
        portfolio = broker.get_portfolio(accounts[0].account_id)
        view = BrokerSnapshotView(
            account_id=portfolio.account_id,
            equity=portfolio.equity,
            cash=portfolio.cash,
            positions=[
                BrokerPositionView(symbol=item.symbol, quantity=item.quantity, market_value=item.market_value)
                for item in portfolio.positions
            ],
            synced_at=_now(),
        )
        self.conn.execute(
            """INSERT INTO broker_snapshots (user_id, payload_json, synced_at) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET payload_json = excluded.payload_json, synced_at = excluded.synced_at""",
            (user_id, view.model_dump_json(), view.synced_at),
        )
        self.conn.commit()
        return view

    def broker_snapshot(self, user_id: str) -> BrokerSnapshotView | None:
        row = self.conn.execute(
            "SELECT payload_json FROM broker_snapshots WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return BrokerSnapshotView.model_validate_json(row["payload_json"])


def _backtest_view(row: sqlite3.Row) -> BacktestView:
    record = row
    metrics = None
    skepticism = None
    equity: list[EquityPoint] = []
    benchmark: list[EquityPoint] = []
    trades: list[TradeView] = []
    if record["metrics_json"]:
        raw = json.loads(record["metrics_json"])
        metrics = MetricsView(
            total_return_pct=raw["total_return_pct"],
            cagr_pct=raw["cagr_pct"],
            sharpe=raw["sharpe"],
            sharpe_se=raw["sharpe_se"],
            max_drawdown_pct=raw["max_drawdown_pct"],
            win_rate_pct=raw["win_rate_pct"],
            exposure_pct=raw["exposure_pct"],
            num_round_trips=raw["num_round_trips"],
            ending_equity=raw["ending_equity"],
        )
    if record["skepticism_json"]:
        skepticism = SkepticismView.model_validate_json(record["skepticism_json"])
    if record["equity_json"]:
        equity = [EquityPoint.model_validate(point) for point in json.loads(record["equity_json"])]
    if record["benchmark_json"]:
        benchmark = [EquityPoint.model_validate(point) for point in json.loads(record["benchmark_json"])]
    if record["trades_json"]:
        trades = [TradeView.model_validate(point) for point in json.loads(record["trades_json"])]
    return BacktestView(
        id=record["id"],
        strategy_id=record["strategy_id"],
        status=record["status"],
        metrics=metrics,
        skepticism=skepticism,
        equity=equity,
        benchmark_equity=benchmark,
        trades=trades,
        error=record["error"],
    )


def _benchmark_curve(bars: list[Bar], starting_cash: float) -> list[dict[str, float | str]]:
    if len(bars) < 2:
        return []
    qty = int(starting_cash // bars[1].open)
    cash = starting_cash - qty * bars[1].open
    return [{"date": bar.timestamp.date().isoformat(), "equity": cash + qty * bar.close} for bar in bars[1:]]

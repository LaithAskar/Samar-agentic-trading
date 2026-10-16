from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

import httpx
from samar_agent.http_model import ProviderName
from samar_data.market import MarketData
from samar_engine.dsl import StrategySpec

from samar_api.live.limits import (
    ALLOWLIST,
    AUTO_PHRASE,
    ENABLE_PHRASE,
    NY,
    REJECT_LIMIT,
    TICKET_MINUTES,
    evaluate,
    market_open,
    sell_proceeds_unsettled,
)
from samar_api.live.model_ticket import ModelOutputError, model_intent
from samar_api.live.public_orders import (
    AccountState,
    BrokerError,
    BrokerRejected,
    PublicOrders,
    order_body,
    preflight_body,
)
from samar_api.live.signal import strategy_intent
from samar_api.live.types import (
    AuditView,
    GuardContext,
    Held,
    Limits,
    LiveSource,
    LiveStatus,
    OrderIntent,
    OrderView,
    SourceChoice,
    TicketView,
)

KeyReader = Callable[[str, str], str | None]
Proposer = Callable[[], OrderIntent | None]
_OPEN = ("submitted", "open")


class LiveBook:
    def __init__(self, conn: sqlite3.Connection, http: httpx.Client, read_key: KeyReader, market: MarketData) -> None:
        self.conn = conn
        self.http = http
        self.read_key = read_key
        self.market = market

    def status(self, user_id: str) -> LiveStatus:
        row = self._settings(user_id)
        enabled = bool(row["enabled"])
        mode = "auto" if row["mode"] == "auto" else "approve"
        banner: Literal["paper", "live", "auto"] = "paper"
        if enabled and mode == "auto":
            banner = "auto"
        elif enabled:
            banner = "live"
        buying = row["buying_power"]
        return LiveStatus(
            enabled=enabled,
            mode=mode,
            banner=banner,
            permission=str(row["permission"]),
            capital_cap=float(row["capital_cap"]),
            max_order_dollars=float(row["max_order_dollars"]),
            max_orders_per_day=None if row["max_orders_per_day"] is None else int(row["max_orders_per_day"]),
            max_orders_per_minute=int(row["max_orders_per_minute"]),
            daily_loss_stop=float(row["daily_loss_stop"]),
            source=_source(str(row["source"])),
            strategy_id=str(row["strategy_id"] or ""),
            model_provider=str(row["model_provider"] or ""),
            model_name=str(row["model_name"] or ""),
            buying_power=None if buying is None else float(buying),
            positions=_held_list(str(row["positions_json"] or "[]")),
            tickets=self._tickets(user_id),
            orders=self._orders(user_id),
            audit=self.audit(user_id),
            halted_reason=str(row["halted_reason"] or ""),
            reject_streak=int(row["reject_streak"]),
            enable_phrase=ENABLE_PHRASE,
            auto_phrase=AUTO_PHRASE,
        )

    def audit(self, user_id: str) -> list[AuditView]:
        rows = self.conn.execute(
            "SELECT id, at, action, detail FROM live_audit WHERE user_id = ? ORDER BY at DESC LIMIT 40",
            (user_id,),
        ).fetchall()
        return [AuditView(id=row["id"], at=row["at"], action=row["action"], detail=row["detail"]) for row in rows]

    def enable(self, user_id: str, phrase: str, now: datetime) -> LiveStatus:
        if phrase != ENABLE_PHRASE:
            raise ValueError("confirmation phrase does not match")
        secret = self._public_secret(user_id)
        try:
            view = self._orders_client(secret).snapshot()
        except BrokerError as exc:
            raise ValueError("broker error") from exc
        self._remember(user_id, view)
        if view.permission != "trade":
            self._audit(user_id, "enable_refused", "this Public key cannot trade", now)
            raise ValueError("this Public key cannot trade")
        self.conn.execute(
            "UPDATE live_settings SET enabled = 1, mode = 'approve', halted_reason = '' WHERE user_id = ?",
            (user_id,),
        )
        self._audit(user_id, "enable", "live mode on, approve each order", now)
        self.conn.commit()
        return self.status(user_id)

    def enable_auto(self, user_id: str, phrase: str, now: datetime) -> LiveStatus:
        if phrase != AUTO_PHRASE:
            raise ValueError("confirmation phrase does not match")
        row = self._settings(user_id)
        if not row["enabled"]:
            raise ValueError("live mode is off")
        if row["permission"] != "trade":
            raise ValueError("this Public key cannot trade")
        self.conn.execute("UPDATE live_settings SET mode = 'auto' WHERE user_id = ?", (user_id,))
        self._audit(user_id, "auto_on", "worker may submit orders inside the limits", now)
        self.conn.commit()
        return self.status(user_id)

    def manual(self, user_id: str, now: datetime) -> LiveStatus:
        self.conn.execute(
            "UPDATE live_settings SET mode = 'approve' WHERE user_id = ?",
            (user_id,),
        )
        self._audit(user_id, "auto_off", "approve each order", now)
        self.conn.commit()
        return self.status(user_id)

    def disable(self, user_id: str, now: datetime) -> LiveStatus:
        self._cancel_open(user_id)
        self.conn.execute(
            """UPDATE live_settings
            SET enabled = 0, mode = 'approve', halted_reason = '' WHERE user_id = ?""",
            (user_id,),
        )
        self._audit(user_id, "disable", "live mode off", now)
        self.conn.commit()
        return self.status(user_id)

    def kill(self, user_id: str, now: datetime) -> LiveStatus:
        self._cancel_open(user_id)
        self.conn.execute(
            """UPDATE live_settings
            SET enabled = 0, mode = 'approve', halted_reason = 'kill switch' WHERE user_id = ?""",
            (user_id,),
        )
        self._audit(user_id, "kill", "kill switch", now)
        self.conn.commit()
        return self.status(user_id)

    def set_limits(
        self,
        user_id: str,
        limits: Limits,
        now: datetime,
    ) -> LiveStatus:
        day_cap = limits.max_orders_per_day
        if limits.capital_cap <= 0 or limits.max_order_dollars <= 0 or limits.daily_loss_stop <= 0:
            raise ValueError("limits must be positive")
        if day_cap is not None and day_cap < 1:
            raise ValueError("daily order limit must be at least 1 or unlimited")
        if not 1 <= limits.max_orders_per_minute <= 30:
            raise ValueError("per-model minute cap must be from 1 to 30")
        if limits.max_order_dollars > limits.capital_cap:
            raise ValueError("per-order cap cannot exceed the capital cap")
        row = self._settings(user_id)
        buying = row["buying_power"]
        if buying is not None and limits.capital_cap > float(buying):
            raise ValueError("capital cap cannot exceed buying power")
        self.conn.execute(
            """UPDATE live_settings
            SET capital_cap = ?, max_order_dollars = ?, max_orders_per_day = ?,
                max_orders_per_minute = ?, daily_loss_stop = ?
            WHERE user_id = ?""",
            (
                limits.capital_cap,
                limits.max_order_dollars,
                limits.max_orders_per_day,
                limits.max_orders_per_minute,
                limits.daily_loss_stop,
                user_id,
            ),
        )
        self._audit(user_id, "limits", f"capital {limits.capital_cap:.2f}", now)
        self.conn.commit()
        return self.status(user_id)

    def set_source(self, user_id: str, choice: SourceChoice, now: datetime) -> LiveStatus:
        if choice.source == "strategy" and not choice.strategy_id:
            raise ValueError("pick a strategy")
        if choice.source == "model" and choice.provider not in {"anthropic", "openrouter", "openai", "nous"}:
            raise ValueError("pick a model provider")
        if choice.source == "model" and not choice.model.strip():
            raise ValueError("pick a model")
        self._settings(user_id)
        self.conn.execute(
            """UPDATE live_settings
            SET source = ?, strategy_id = ?, model_provider = ?, model_name = ?
            WHERE user_id = ?""",
            (choice.source, choice.strategy_id, choice.provider, choice.model, user_id),
        )
        self._audit(user_id, "source", choice.source, now)
        self.conn.commit()
        return self.status(user_id)

    def propose(self, user_id: str, intent: OrderIntent, now: datetime) -> TicketView:
        self._expire(user_id, now)
        row = self._settings(user_id)
        if not row["enabled"]:
            raise ValueError("live mode is off")
        ctx = self._context(user_id, now, None, intent.model)
        result = evaluate(intent, ctx)
        if not result.ok:
            self._audit(user_id, "reject", result.reason, now)
            self.conn.commit()
            if result.halt:
                self.halt(user_id, result.reason, now)
            raise ValueError(result.reason)
        ticket_id = f"tkt_{uuid.uuid4().hex[:12]}"
        expires = now + timedelta(minutes=TICKET_MINUTES)
        est = round(intent.quantity * intent.limit_price, 2)
        symbol = intent.symbol.upper()
        day_start = now.astimezone(NY).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        # One statement checks for a working order and inserts, so a worker and /live/check cannot both pass.
        inserted = self.conn.execute(
            """INSERT INTO live_tickets
            (id, user_id, symbol, side, qty, limit_price, est_cost, reason, model, status, created_at, expires_at)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM live_tickets
                WHERE user_id = ? AND symbol = ? AND side = ? AND status IN ('pending', 'sending')
            )
            AND NOT EXISTS (
                SELECT 1 FROM live_orders
                WHERE user_id = ? AND symbol = ? AND side = ? AND status IN ('submitted', 'open') AND created_at >= ?
            )""",
            (
                ticket_id,
                user_id,
                symbol,
                intent.side,
                intent.quantity,
                intent.limit_price,
                est,
                intent.reason,
                intent.model,
                now.isoformat(),
                expires.isoformat(),
                user_id,
                symbol,
                intent.side,
                user_id,
                symbol,
                intent.side,
                day_start.isoformat(),
            ),
        ).rowcount
        if inserted != 1:
            self._audit(user_id, "working", f"{symbol} already working", now)
            self.conn.commit()
            raise ValueError(f"{symbol} {intent.side} is already working")
        self._audit(user_id, "ticket", f"{intent.side} {intent.quantity} {symbol}", now)
        self.conn.commit()
        if row["mode"] == "auto":
            self._send(user_id, ticket_id, now)
        view = self._ticket(user_id, ticket_id)
        if view is None:
            raise KeyError(ticket_id)
        return view

    def approve(self, user_id: str, ticket_id: str, now: datetime) -> TicketView:
        self._expire(user_id, now)
        ticket = self._ticket_row(user_id, ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        if ticket["status"] == "expired" or _parse(str(ticket["expires_at"])) <= now:
            self.conn.execute("UPDATE live_tickets SET status = 'expired' WHERE id = ?", (ticket_id,))
            self._audit(user_id, "expired", ticket_id, now)
            self.conn.commit()
            raise ValueError("ticket expired")
        if ticket["status"] == "sent":
            view = self._ticket(user_id, ticket_id)
            if view is None:
                raise KeyError(ticket_id)
            return view
        if ticket["status"] != "pending":
            raise ValueError("ticket is not pending")
        self._send(user_id, ticket_id, now)
        view = self._ticket(user_id, ticket_id)
        if view is None:
            raise KeyError(ticket_id)
        return view

    def halt(self, user_id: str, reason: str, now: datetime) -> None:
        self._cancel_open(user_id)
        self.conn.execute(
            """UPDATE live_settings
            SET enabled = 0, mode = 'approve', halted_reason = ?, reject_streak = 0
            WHERE user_id = ?""",
            (reason, user_id),
        )
        self._audit(user_id, "halt", reason, now)
        self.conn.commit()

    def run_due(self, now: datetime) -> int:
        rows = self.conn.execute(
            "SELECT user_id FROM live_settings WHERE enabled = 1 AND mode = 'auto'",
        ).fetchall()
        placed = 0
        for row in rows:
            placed += self.run_cycle(str(row["user_id"]), now, None)
        return placed

    def run_cycle(self, user_id: str, now: datetime, proposer: Proposer | None) -> int:
        row = self._settings(user_id)
        if not row["enabled"] or row["mode"] != "auto":
            return 0
        secret = self._public_secret(user_id)
        client = self._orders_client(secret)
        try:
            view = client.snapshot()
        except BrokerError:
            self.halt(user_id, "broker error", now)
            return 0
        self._remember(user_id, view)
        if view.permission != "trade":
            self.halt(user_id, "this Public key cannot trade", now)
            return 0
        if _unexpected(view.positions):
            self.halt(user_id, "unexpected position", now)
            return 0
        pnl = self._mark_pnl(user_id, view.equity, now)
        if not market_open(now):
            self._audit(user_id, "market_closed", "no order", now)
            self.conn.commit()
            return 0
        if pnl <= -float(row["daily_loss_stop"]):
            self.halt(user_id, "daily loss stop is hit", now)
            return 0
        try:
            intent = self._intent(user_id, view, proposer)
        except ModelOutputError:
            self._audit(user_id, "model_invalid", "model output invalid", now)
            self.conn.commit()
            return 0
        except BrokerError:
            self.halt(user_id, "broker error", now)
            return 0
        if intent is None:
            self._audit(user_id, "flat", "no order", now)
            self.conn.commit()
            return 0
        if self._working(user_id, intent.symbol.upper(), intent.side):
            self._audit(user_id, "working", f"{intent.symbol} already working", now)
            self.conn.commit()
            return 0
        try:
            self.propose(user_id, intent, now)
        except ValueError:
            return 0
        sent = self.conn.execute(
            "SELECT status FROM live_tickets WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if sent is not None and sent["status"] == "sent":
            return 1
        return 0

    def _intent(self, user_id: str, view: AccountState, proposer: Proposer | None) -> OrderIntent | None:
        if proposer is not None:
            return proposer()
        row = self._settings(user_id)
        source = str(row["source"])
        if source == "off":
            return None
        if source == "strategy":
            return self._strategy_intent(user_id, view)
        return self._model_intent(user_id)

    def _strategy_intent(self, user_id: str, view: AccountState) -> OrderIntent | None:
        row = self._settings(user_id)
        spec_row = self.conn.execute(
            "SELECT dsl_json FROM strategies WHERE id = ? AND user_id = ?",
            (row["strategy_id"], user_id),
        ).fetchone()
        if spec_row is None:
            return None
        spec = StrategySpec.model_validate_json(spec_row["dsl_json"])
        symbol = spec.universe[0]
        quote = self._orders_client(self._public_secret(user_id)).quote(view.account_id, symbol)
        bars = self.market.bars(symbol, date(2020, 1, 1), date(2026, 12, 31))
        held = 0.0
        for position in view.positions:
            if position.symbol.upper() == symbol.upper():
                held = position.quantity
        limits = _limits(row)
        return strategy_intent(spec, bars, quote, limits, held)

    def _model_intent(self, user_id: str) -> OrderIntent:
        row = self._settings(user_id)
        provider = cast(ProviderName, str(row["model_provider"]))
        model = str(row["model_name"])
        key = self.read_key(user_id, provider)
        if key is None:
            raise ModelOutputError("model output invalid")
        return model_intent(provider, model, key, self.http)

    def _send(self, user_id: str, ticket_id: str, now: datetime) -> None:
        claimed = self.conn.execute(
            "UPDATE live_tickets SET status = 'sending' WHERE id = ? AND user_id = ? AND status = 'pending'",
            (ticket_id, user_id),
        ).rowcount
        self.conn.commit()
        if claimed != 1:
            if self._ticket_row(user_id, ticket_id) is None:
                raise KeyError(ticket_id)
            raise ValueError("ticket is not pending")
        try:
            self._send_claimed(user_id, ticket_id, now)
        finally:
            # A failure that set no final status leaves the ticket retryable with the same order id.
            self.conn.execute(
                "UPDATE live_tickets SET status = 'pending' WHERE id = ? AND status = 'sending'",
                (ticket_id,),
            )
            self.conn.commit()

    def _send_claimed(self, user_id: str, ticket_id: str, now: datetime) -> None:
        ticket = self._ticket_row(user_id, ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        order_id = str(ticket["order_id"] or "") or str(uuid.uuid4())
        self.conn.execute("UPDATE live_tickets SET order_id = ? WHERE id = ?", (order_id, ticket_id))
        self.conn.commit()
        existing = self.conn.execute("SELECT id FROM live_orders WHERE id = ?", (order_id,)).fetchone()
        if existing is not None:
            self.conn.execute("UPDATE live_tickets SET status = 'sent' WHERE id = ?", (ticket_id,))
            self._audit(user_id, "sent", "retry reused the order id", now)
            self.conn.commit()
            return
        secret = self._public_secret(user_id)
        client = self._orders_client(secret)
        try:
            view = client.snapshot()
        except BrokerError:
            self.halt(user_id, "broker error", now)
            raise ValueError("broker error") from None
        self._remember(user_id, view)
        if _unexpected(view.positions):
            self.conn.execute("UPDATE live_tickets SET status = 'halted' WHERE id = ?", (ticket_id,))
            self.halt(user_id, "unexpected position", now)
            raise ValueError("unexpected position")
        self._mark_pnl(user_id, view.equity, now)
        ctx = self._context(user_id, now, view, str(ticket["model"]))
        intent = OrderIntent(
            symbol=str(ticket["symbol"]),
            side="BUY" if ticket["side"] == "BUY" else "SELL",
            quantity=int(ticket["qty"]),
            limit_price=float(ticket["limit_price"]),
            reason=str(ticket["reason"]),
            model=str(ticket["model"]),
        )
        result = evaluate(intent, ctx)
        if not result.ok:
            self.conn.execute("UPDATE live_tickets SET status = 'rejected' WHERE id = ?", (ticket_id,))
            self._audit(user_id, "reject", result.reason, now)
            self.conn.commit()
            if result.halt:
                self.halt(user_id, result.reason, now)
            raise ValueError(result.reason)
        body = order_body(order_id, intent.symbol.upper(), intent.side, intent.quantity, intent.limit_price)
        try:
            client.preflight(view.account_id, preflight_body(body))
            client.place_order(view.account_id, body)
        except BrokerRejected:
            self.conn.execute("UPDATE live_tickets SET status = 'rejected' WHERE id = ?", (ticket_id,))
            self.conn.commit()
            self._rejection(user_id, now)
            raise ValueError("broker rejected the order") from None
        except BrokerError:
            self.conn.execute("UPDATE live_tickets SET status = 'halted' WHERE id = ?", (ticket_id,))
            self.conn.commit()
            self.halt(user_id, "broker error", now)
            raise ValueError("broker error") from None
        self.conn.execute(
            """INSERT INTO live_orders
            (id, user_id, ticket_id, symbol, side, qty, limit_price, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?)""",
            (
                order_id,
                user_id,
                ticket_id,
                intent.symbol.upper(),
                intent.side,
                intent.quantity,
                intent.limit_price,
                now.isoformat(),
            ),
        )
        self.conn.execute("UPDATE live_tickets SET status = 'sent' WHERE id = ?", (ticket_id,))
        self.conn.execute("UPDATE live_settings SET reject_streak = 0 WHERE user_id = ?", (user_id,))
        self._audit(user_id, "sent", order_id, now)
        self.conn.commit()

    def _rejection(self, user_id: str, now: datetime) -> None:
        row = self._settings(user_id)
        streak = int(row["reject_streak"]) + 1
        self.conn.execute(
            "UPDATE live_settings SET reject_streak = ? WHERE user_id = ?",
            (streak, user_id),
        )
        self._audit(user_id, "broker_rejected", str(streak), now)
        self.conn.commit()
        if streak >= REJECT_LIMIT:
            self.halt(user_id, "repeated rejections", now)

    def _context(self, user_id: str, now: datetime, view: AccountState | None, model: str) -> GuardContext:
        row = self._settings(user_id)
        positions = view.positions if view is not None else tuple(_held_list(str(row["positions_json"] or "[]")))
        buying = view.buying_power if view is not None else float(row["buying_power"] or 0)
        if view is not None and view.settled_cash is not None:
            settled: float | None = view.settled_cash
        elif row["settled_cash"] is not None and view is None:
            settled = float(row["settled_cash"])
        else:
            settled = max(0.0, buying - self._unsettled_sells(user_id, now))
        return GuardContext(
            live_enabled=bool(row["enabled"]),
            limits=_limits(row),
            buying_power=buying,
            positions=positions,
            day_pnl=float(row["day_pnl"]),
            orders_today=self._orders_today(user_id, now),
            orders_last_minute=self._orders_last_minute(user_id, model, now),
            settled_cash=settled,
            open_buys=self._open_buys(user_id, now),
            now=now,
            allowlist=ALLOWLIST,
        )

    def _mark_pnl(self, user_id: str, equity: float, now: datetime) -> float:
        row = self._settings(user_id)
        day = now.astimezone(NY).date().isoformat()
        if str(row["day_key"] or "") != day or row["day_start_equity"] is None:
            self.conn.execute(
                "UPDATE live_settings SET day_key = ?, day_start_equity = ?, day_pnl = 0 WHERE user_id = ?",
                (day, equity, user_id),
            )
            self.conn.commit()
            return 0.0
        pnl = equity - float(row["day_start_equity"])
        self.conn.execute("UPDATE live_settings SET day_pnl = ? WHERE user_id = ?", (pnl, user_id))
        self.conn.commit()
        return pnl

    def _orders_today(self, user_id: str, now: datetime) -> int:
        local = now.astimezone(NY)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        end = start + timedelta(days=1)
        row = self.conn.execute(
            """SELECT COUNT(*) AS n FROM live_orders
            WHERE user_id = ? AND created_at >= ? AND created_at < ?""",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def _orders_last_minute(self, user_id: str, model: str, now: datetime) -> int:
        start = (now - timedelta(seconds=60)).isoformat()
        row = self.conn.execute(
            """SELECT COUNT(*) AS n FROM live_orders AS orders
            JOIN live_tickets AS tickets ON tickets.id = orders.ticket_id
            WHERE orders.user_id = ? AND tickets.model = ?
            AND orders.created_at > ? AND orders.created_at <= ?""",
            (user_id, model, start, now.isoformat()),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def _open_buys(self, user_id: str, now: datetime) -> float:
        """Buy orders still working today. Orders are DAY orders, so earlier ones have expired or filled."""
        local = now.astimezone(NY)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        row = self.conn.execute(
            """SELECT COALESCE(SUM(qty * limit_price), 0) AS total FROM live_orders
            WHERE user_id = ? AND side = 'BUY' AND status IN ('submitted', 'open') AND created_at >= ?""",
            (user_id, start.isoformat()),
        ).fetchone()
        return float(row["total"]) if row is not None else 0.0

    def _unsettled_sells(self, user_id: str, now: datetime) -> float:
        rows = self.conn.execute(
            """SELECT qty, limit_price, created_at FROM live_orders
            WHERE user_id = ? AND side = 'SELL' AND status IN ('submitted', 'open', 'filled')""",
            (user_id,),
        ).fetchall()
        total = 0.0
        for row in rows:
            sold_at = _parse(str(row["created_at"]))
            if sell_proceeds_unsettled(sold_at, now):
                total += float(row["qty"]) * float(row["limit_price"])
        return total

    def _working(self, user_id: str, symbol: str, side: str) -> bool:
        order = self.conn.execute(
            """SELECT id FROM live_orders
            WHERE user_id = ? AND symbol = ? AND side = ? AND status IN ('submitted', 'open')""",
            (user_id, symbol, side),
        ).fetchone()
        if order is not None:
            return True
        ticket = self.conn.execute(
            """SELECT id FROM live_tickets
            WHERE user_id = ? AND symbol = ? AND side = ? AND status IN ('pending', 'sending')""",
            (user_id, symbol, side),
        ).fetchone()
        return ticket is not None

    def _cancel_open(self, user_id: str) -> None:
        row = self._settings(user_id)
        account_id = str(row["account_id"] or "")
        orders = self.conn.execute(
            "SELECT id FROM live_orders WHERE user_id = ? AND status IN ('submitted', 'open')",
            (user_id,),
        ).fetchall()
        secret = self.read_key(user_id, "public_com")
        client = self._orders_client(secret) if secret and account_id else None
        for order in orders:
            if client is not None:
                try:
                    client.cancel_order(account_id, str(order["id"]))
                except BrokerError:
                    self.conn.execute(
                        "UPDATE live_orders SET status = 'cancel_failed' WHERE id = ?",
                        (order["id"],),
                    )
                    continue
            self.conn.execute("UPDATE live_orders SET status = 'cancelled' WHERE id = ?", (order["id"],))
        self.conn.commit()

    def _remember(self, user_id: str, view: AccountState) -> None:
        self._settings(user_id)
        payload = json.dumps([position.model_dump() for position in view.positions])
        self.conn.execute(
            """UPDATE live_settings
            SET permission = ?, buying_power = ?, settled_cash = ?, account_id = ?, positions_json = ?, equity = ?
            WHERE user_id = ?""",
            (view.permission, view.buying_power, view.settled_cash, view.account_id, payload, view.equity, user_id),
        )
        self.conn.commit()

    def _settings(self, user_id: str) -> sqlite3.Row:
        self.conn.execute("INSERT OR IGNORE INTO live_settings (user_id) VALUES (?)", (user_id,))
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM live_settings WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        return row

    def _public_secret(self, user_id: str) -> str:
        secret = self.read_key(user_id, "public_com")
        if secret is None:
            raise ValueError("save a Public.com key first")
        return secret

    def _orders_client(self, secret: str) -> PublicOrders:
        return PublicOrders(secret, self.http)

    def _expire(self, user_id: str, now: datetime) -> None:
        rows = self.conn.execute(
            "SELECT id, expires_at FROM live_tickets WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        ).fetchall()
        for row in rows:
            if _parse(str(row["expires_at"])) <= now:
                self.conn.execute("UPDATE live_tickets SET status = 'expired' WHERE id = ?", (row["id"],))
        self.conn.commit()

    def _tickets(self, user_id: str) -> list[TicketView]:
        rows = self.conn.execute(
            """SELECT * FROM live_tickets
            WHERE user_id = ? AND status = 'pending' ORDER BY created_at""",
            (user_id,),
        ).fetchall()
        return [_ticket_view(row) for row in rows]

    def _orders(self, user_id: str) -> list[OrderView]:
        rows = self.conn.execute(
            "SELECT * FROM live_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user_id,),
        ).fetchall()
        return [
            OrderView(
                id=row["id"],
                symbol=row["symbol"],
                side=row["side"],
                quantity=int(row["qty"]),
                limit_price=float(row["limit_price"]),
                status=row["status"],
            )
            for row in rows
        ]

    def _ticket(self, user_id: str, ticket_id: str) -> TicketView | None:
        row = self._ticket_row(user_id, ticket_id)
        if row is None:
            return None
        return _ticket_view(row)

    def _ticket_row(self, user_id: str, ticket_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM live_tickets WHERE id = ? AND user_id = ?",
            (ticket_id, user_id),
        ).fetchone()

    def _audit(self, user_id: str, action: str, detail: str, now: datetime) -> None:
        self.conn.execute(
            "INSERT INTO live_audit (id, user_id, at, action, detail) VALUES (?, ?, ?, ?, ?)",
            (f"aud_{uuid.uuid4().hex[:12]}", user_id, now.isoformat(), action, detail),
        )


def _limits(row: sqlite3.Row) -> Limits:
    raw_day = row["max_orders_per_day"]
    return Limits(
        capital_cap=float(row["capital_cap"]),
        max_order_dollars=float(row["max_order_dollars"]),
        max_orders_per_day=None if raw_day is None else int(raw_day),
        max_orders_per_minute=int(row["max_orders_per_minute"]),
        daily_loss_stop=float(row["daily_loss_stop"]),
    )


def _ticket_view(row: sqlite3.Row) -> TicketView:
    return TicketView(
        id=row["id"],
        symbol=row["symbol"],
        side=row["side"],
        quantity=int(row["qty"]),
        limit_price=float(row["limit_price"]),
        est_cost=float(row["est_cost"]),
        reason=row["reason"],
        model=row["model"],
        status=row["status"],
        expires_at=row["expires_at"],
    )


def _held_list(payload: str) -> list[Held]:
    raw = json.loads(payload)
    if not isinstance(raw, list):
        return []
    return [Held.model_validate(item) for item in raw if isinstance(item, dict)]


def _unexpected(positions: tuple[Held, ...]) -> bool:
    for position in positions:
        if position.quantity < 0:
            return True
        if position.instrument_type not in {"", "EQUITY"}:
            return True
        if position.symbol.upper() not in ALLOWLIST:
            return True
    return False


def _source(value: str) -> LiveSource:
    if value == "strategy":
        return "strategy"
    if value == "model":
        return "model"
    return "off"


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed

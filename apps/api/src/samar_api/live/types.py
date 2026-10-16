from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SideName = Literal["BUY", "SELL"]
LiveMode = Literal["approve", "auto"]
LiveSource = Literal["off", "strategy", "model"]
Banner = Literal["paper", "live", "auto"]


class Limits(BaseModel):
    capital_cap: float = 200.0
    max_order_dollars: float = 200.0
    max_orders_per_day: int | None = 4
    max_orders_per_minute: int = 2
    daily_loss_stop: float = 50.0


class Held(BaseModel):
    symbol: str
    quantity: float
    instrument_type: str = "EQUITY"
    market_value: float | None = None


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: SideName
    quantity: int
    limit_price: float
    reason: str
    model: str = "manual"
    use_margin: bool = False


class GuardContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live_enabled: bool
    limits: Limits
    buying_power: float
    positions: tuple[Held, ...] = ()
    day_pnl: float = 0.0
    orders_today: int = 0
    orders_last_minute: int = 0
    settled_cash: float | None = None
    open_buys: float = 0.0
    now: datetime
    allowlist: frozenset[str] = Field(default_factory=frozenset)


class GuardResult(BaseModel):
    ok: bool
    reason: str
    halt: bool = False


class TicketView(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    est_cost: float
    reason: str
    model: str
    status: str
    expires_at: str


class OrderView(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    status: str


class AuditView(BaseModel):
    id: str
    at: str
    action: str
    detail: str


class SourceChoice(BaseModel):
    source: LiveSource
    strategy_id: str = ""
    provider: str = ""
    model: str = ""


class LiveStatus(BaseModel):
    enabled: bool
    mode: LiveMode
    banner: Banner
    permission: str
    capital_cap: float
    max_order_dollars: float
    max_orders_per_day: int | None
    max_orders_per_minute: int
    daily_loss_stop: float
    source: LiveSource
    strategy_id: str
    model_provider: str
    model_name: str
    buying_power: float | None
    positions: list[Held]
    tickets: list[TicketView]
    orders: list[OrderView]
    audit: list[AuditView]
    halted_reason: str
    reject_streak: int
    enable_phrase: str
    auto_phrase: str

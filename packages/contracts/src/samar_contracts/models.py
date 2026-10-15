from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class StrategyView(BaseModel):
    id: str
    name: str
    universe: list[str]
    dsl: dict[str, object]


class EquityPoint(BaseModel):
    date: str
    equity: float


class TradeView(BaseModel):
    date: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: float


class MetricsView(BaseModel):
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sharpe_se: float
    max_drawdown_pct: float
    win_rate_pct: float
    exposure_pct: float
    num_round_trips: int
    ending_equity: float


class SkepticismView(BaseModel):
    beat_benchmark: bool
    benchmark_name: str
    strategy_return_pct: float
    benchmark_return_pct: float
    sharpe: float
    sharpe_se: float
    sharpe_p_value: float
    num_round_trips: int
    sample_days: int
    warnings: list[str]


class BacktestView(BaseModel):
    id: str
    strategy_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    metrics: MetricsView | None
    skepticism: SkepticismView | None
    equity: list[EquityPoint]
    benchmark_equity: list[EquityPoint]
    trades: list[TradeView]
    error: str | None


class SecretStatus(BaseModel):
    kind: Literal["anthropic", "openrouter", "openai", "nous", "public_com"]
    last4: str
    status: Literal["valid", "invalid", "revoked"]
    validated_at: str


class PaperPositionView(BaseModel):
    ticker: str
    quantity: float
    avg_price: float
    last_price: float
    market_value: float


class PaperAccountView(BaseModel):
    cash: float
    equity: float
    starting_cash: float
    pnl: float
    positions: list[PaperPositionView]
    orders: list[TradeView]


class ProposalView(BaseModel):
    id: str
    kind: Literal["create_strategy", "run_backtest"]
    status: Literal["pending", "approved", "rejected"]
    payload: dict[str, str]


class BrokerPositionView(BaseModel):
    symbol: str
    quantity: float
    market_value: float


class ArenaProposalView(BaseModel):
    index: int
    ok: bool
    error: str | None
    train_sharpe: float | None
    spec_name: str | None


class ArenaEntryView(BaseModel):
    contestant: str
    model: str
    status: str
    n_trials: int
    n_failures: int
    tokens_in: int
    tokens_out: int
    rank: int | None
    deflated_sharpe: float | None
    test_sharpe: float | None
    test_sharpe_se: float | None
    test_max_drawdown_pct: float | None
    turnover: int | None
    fold_sharpes: list[float]
    skepticism: SkepticismView | None
    equity: list[EquityPoint]
    proposals: list[ArenaProposalView]


class ArenaRunView(BaseModel):
    id: str
    status: str
    ticker: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    budget_proposals: int
    token_cap: int
    entries: list[ArenaEntryView]
    error: str | None


class BrokerSnapshotView(BaseModel):
    label: Literal["REAL ACCOUNT · read-only"] = "REAL ACCOUNT · read-only"
    account_id: str
    equity: float
    cash: float
    positions: list[BrokerPositionView]
    synced_at: str

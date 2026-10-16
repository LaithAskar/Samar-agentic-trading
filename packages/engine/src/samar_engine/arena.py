from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from random import Random

from samar_engine.backtest.engine import BacktestEngine
from samar_engine.backtest.metrics import compute_metrics, daily_returns, sharpe_ratio, sharpe_standard_error
from samar_engine.backtest.rigor import buy_and_hold, sharpe_significance
from samar_engine.core.events import Bar
from samar_engine.dsl import StrategySpec, compile_strategy, rsi_mean_rev_spec, sma_cross_spec
from samar_engine.skepticism import Skepticism, build_skepticism

TRAIN_START = date(2020, 1, 2)
TRAIN_END = date(2022, 12, 30)
TEST_START = date(2023, 1, 3)
TEST_END = date(2024, 12, 31)
FOLD_1 = (date(2023, 1, 3), date(2023, 12, 29))
FOLD_2 = (date(2024, 1, 2), date(2024, 12, 31))
STARTING_CASH = 100_000.0


@dataclass(frozen=True)
class HistorySplit:
    train: list[Bar]
    test: list[Bar]
    folds: tuple[list[Bar], list[Bar]]


def split_history(bars: list[Bar]) -> HistorySplit:
    """Train is the first 60 percent of the bars. The rest is held out and folded in half."""
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    if len(ordered) < 80:
        raise ValueError("need at least 80 daily bars to split train and test")
    cut = int(len(ordered) * 0.6)
    train = ordered[:cut]
    test = ordered[cut:]
    if len(train) < 50 or len(test) < 20:
        raise ValueError("train needs 50 bars and the held-out window needs 20")
    mid = len(test) // 2
    if mid < 2 or len(test) - mid < 2:
        raise ValueError("held-out window is too short to fold")
    return HistorySplit(train, test, (test[:mid], test[mid:]))


SLIPPAGE_BPS = 5.0
RANDOM_SEED = 1


@dataclass(frozen=True)
class Scorecard:
    sharpe: float
    sharpe_se: float
    max_drawdown_pct: float
    turnover: int
    total_return_pct: float
    p_value: float
    sample_days: int
    benchmark_return_pct: float
    equity: tuple[tuple[str, float], ...]
    skepticism: Skepticism


@dataclass(frozen=True)
class RankRow:
    label: str
    deflated_sharpe: float | None
    max_drawdown_pct: float | None
    turnover: int | None


def deflated_sharpe(sharpe: float, sharpe_se: float, n_trials: int) -> float:
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")
    if math.isnan(sharpe) or math.isnan(sharpe_se):
        return float("-inf")
    return sharpe - sharpe_se * math.sqrt(2.0 * math.log(n_trials))


def rank_labels(rows: list[RankRow]) -> list[str]:
    def sort_key(row: RankRow) -> tuple[bool, float, float, int, str]:
        missing = row.deflated_sharpe is None
        drawdown = row.max_drawdown_pct if row.max_drawdown_pct is not None else 1e9
        turnover = row.turnover if row.turnover is not None else 10**9
        score = 0.0 if row.deflated_sharpe is None else -row.deflated_sharpe
        return (missing, score, drawdown, turnover, row.label)

    return [row.label for row in sorted(rows, key=sort_key)]


def random_specs(n: int, ticker: str = "AAPL", seed: int = RANDOM_SEED) -> list[StrategySpec]:
    if n < 1:
        raise ValueError("n must be at least 1")
    catalog = (
        sma_cross_spec(ticker, 10, 30),
        sma_cross_spec(ticker, 20, 50),
        sma_cross_spec(ticker, 5, 20),
        rsi_mean_rev_spec(ticker),
    )
    rng = Random(seed)  # noqa: S311
    return [catalog[rng.randrange(len(catalog))] for _ in range(n)]


def score_spec(spec: StrategySpec, bars: list[Bar]) -> Scorecard:
    if len(bars) < 2:
        raise ValueError("window needs at least two bars")
    result = BacktestEngine(starting_cash=STARTING_CASH, slippage_bps=SLIPPAGE_BPS).run(
        compile_strategy(spec),
        spec.universe[0],
        iter(bars),
    )
    metrics = compute_metrics(result.portfolio)
    benchmark = buy_and_hold(bars, starting_cash=STARTING_CASH)
    equity_values = [point[1] for point in result.portfolio.equity_curve]
    returns = daily_returns(equity_values)
    _t_stat, p_value = sharpe_significance(returns)
    sample_days = (bars[-1].timestamp - bars[0].timestamp).days
    skepticism = build_skepticism(metrics, benchmark, p_value, sample_days)
    equity = tuple((ts.date().isoformat(), value) for ts, value in result.portfolio.equity_curve)
    drawdown = abs(metrics.max_drawdown_pct)
    return Scorecard(
        sharpe=metrics.sharpe,
        sharpe_se=metrics.sharpe_se,
        max_drawdown_pct=drawdown,
        turnover=metrics.num_round_trips,
        total_return_pct=metrics.total_return_pct,
        p_value=p_value,
        sample_days=sample_days,
        benchmark_return_pct=benchmark.total_return_pct,
        equity=equity,
        skepticism=skepticism,
    )


def score_buy_and_hold(bars: list[Bar]) -> Scorecard:
    if len(bars) < 2:
        raise ValueError("window needs at least two bars")
    benchmark = buy_and_hold(bars, starting_cash=STARTING_CASH)
    fill_price = bars[1].open
    qty = int(STARTING_CASH // fill_price)
    cash = STARTING_CASH - qty * fill_price
    points = [(bar.timestamp.date().isoformat(), cash + qty * bar.close) for bar in bars[1:]]
    values = [value for _date, value in points]
    returns = daily_returns(values)
    sharpe = sharpe_ratio(returns)
    sharpe_se = sharpe_standard_error(returns)
    _t_stat, p_value = sharpe_significance(returns)
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, (value / peak) - 1.0)
    sample_days = (bars[-1].timestamp - bars[1].timestamp).days
    skepticism = Skepticism(
        beat_benchmark=False,
        benchmark_name="buy_and_hold",
        strategy_return_pct=benchmark.total_return_pct,
        benchmark_return_pct=benchmark.total_return_pct,
        sharpe=sharpe,
        sharpe_se=sharpe_se,
        sharpe_p_value=p_value,
        num_round_trips=0,
        sample_days=sample_days,
        warnings=["Baseline. No model searched this rule.", "Historical backtest. Not a prediction."],
    )
    return Scorecard(
        sharpe=sharpe,
        sharpe_se=sharpe_se,
        max_drawdown_pct=abs(max_dd * 100),
        turnover=0,
        total_return_pct=benchmark.total_return_pct,
        p_value=p_value,
        sample_days=sample_days,
        benchmark_return_pct=benchmark.total_return_pct,
        equity=tuple(points),
        skepticism=skepticism,
    )


def best_train_index(train_sharpes: list[float | None]) -> int | None:
    best_index: int | None = None
    best_value = float("-inf")
    for index, value in enumerate(train_sharpes):
        if value is None:
            continue
        if value > best_value:
            best_value = value
            best_index = index
    return best_index

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from samar_engine.backtest.metrics import TRADING_DAYS_PER_YEAR, population_sharpe
from samar_engine.core.events import Bar


@dataclass(frozen=True)
class BenchmarkResult:
    symbol: str
    name: str
    start_equity: float
    end_equity: float
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    volatility_pct: float
    max_drawdown_pct: float
    exposure_pct: float


def _metrics_from_equity(
    *,
    symbol: str,
    name: str,
    equity_series: list[float],
    timestamps: list[datetime],
    starting_cash: float,
    exposure_count: int,
) -> BenchmarkResult:
    if len(equity_series) < 2:
        return BenchmarkResult(symbol, name, starting_cash, starting_cash, 0, 0, 0, 0, 0, 0)

    start_eq = equity_series[0]
    end_eq = equity_series[-1]
    total_ret = end_eq / start_eq - 1.0 if start_eq > 0 else 0.0
    days = (timestamps[-1] - timestamps[0]).days
    years = max(days / 365.25, 1e-9)
    cagr = (end_eq / start_eq) ** (1 / years) - 1.0 if start_eq > 0 else 0.0
    rets: list[float] = []
    for prev, cur in zip(equity_series, equity_series[1:], strict=False):
        rets.append(0.0 if prev == 0 else (cur / prev) - 1.0)
    sigma = 0.0
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((value - mean) ** 2 for value in rets) / (len(rets) - 1)
        sigma = math.sqrt(var)
    if sigma > 0:
        sharpe = (sum(rets) / len(rets)) / sigma * math.sqrt(TRADING_DAYS_PER_YEAR)
        volatility = sigma * math.sqrt(TRADING_DAYS_PER_YEAR)
    else:
        sharpe = 0.0
        volatility = 0.0
    peak = equity_series[0]
    max_dd = 0.0
    for value in equity_series:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, (value / peak) - 1.0)
    exposure_pct = exposure_count / len(equity_series) * 100.0 if equity_series else 0.0
    return BenchmarkResult(
        symbol=symbol,
        name=name,
        start_equity=starting_cash,
        end_equity=end_eq,
        total_return_pct=total_ret * 100,
        cagr_pct=cagr * 100,
        sharpe=sharpe,
        volatility_pct=volatility * 100,
        max_drawdown_pct=max_dd * 100,
        exposure_pct=exposure_pct,
    )


def buy_and_hold(bars: list[Bar], starting_cash: float) -> BenchmarkResult:
    """Buy at the second bar's open and hold. Matches a signal on bar 0."""
    symbol = bars[0].symbol if bars else ""
    if len(bars) < 2:
        return BenchmarkResult(symbol, "buy_and_hold", starting_cash, starting_cash, 0, 0, 0, 0, 0, 0)
    fill_price = bars[1].open
    qty = int(starting_cash // fill_price)
    cash = starting_cash - qty * fill_price
    equity_series = [cash + qty * bar.close for bar in bars[1:]]
    timestamps = [bar.timestamp for bar in bars[1:]]
    return _metrics_from_equity(
        symbol=symbol,
        name="buy_and_hold",
        equity_series=equity_series,
        timestamps=timestamps,
        starting_cash=starting_cash,
        exposure_count=len(equity_series) if qty > 0 else 0,
    )


def _all_in_out_baseline(
    bars: list[Bar],
    starting_cash: float,
    name: str,
    desired_long: list[bool],
) -> BenchmarkResult:
    symbol = bars[0].symbol if bars else ""
    if len(bars) < 2:
        return BenchmarkResult(symbol, name, starting_cash, starting_cash, 0, 0, 0, 0, 0, 0)
    cash = starting_cash
    qty = 0
    equity_series: list[float] = []
    timestamps: list[datetime] = []
    exposure_count = 0
    target_long = False
    for i, bar in enumerate(bars):
        if i > 0:
            if target_long and qty == 0:
                qty = int(cash // bar.open)
                cash -= qty * bar.open
            elif not target_long and qty > 0:
                cash += qty * bar.open
                qty = 0
        equity = cash + qty * bar.close
        equity_series.append(equity)
        timestamps.append(bar.timestamp)
        if qty > 0:
            exposure_count += 1
        target_long = desired_long[i] if i < len(desired_long) else target_long
    return _metrics_from_equity(
        symbol=symbol,
        name=name,
        equity_series=equity_series,
        timestamps=timestamps,
        starting_cash=starting_cash,
        exposure_count=exposure_count,
    )


def sma_crossover_baseline(
    bars: list[Bar],
    starting_cash: float,
    fast: int = 20,
    slow: int = 50,
) -> BenchmarkResult:
    if fast >= slow:
        raise ValueError("fast must be < slow")
    closes = [bar.close for bar in bars]
    desired: list[bool] = []
    for i in range(len(closes)):
        if i + 1 < slow:
            desired.append(False)
            continue
        fast_sma = sum(closes[i + 1 - fast : i + 1]) / fast
        slow_sma = sum(closes[i + 1 - slow : i + 1]) / slow
        desired.append(fast_sma > slow_sma)
    return _all_in_out_baseline(bars, starting_cash, f"sma_{fast}_{slow}", desired)


def momentum_baseline(
    bars: list[Bar],
    starting_cash: float,
    lookback: int = 20,
) -> BenchmarkResult:
    closes = [bar.close for bar in bars]
    desired = [False if i < lookback else closes[i] > closes[i - lookback] for i in range(len(closes))]
    return _all_in_out_baseline(bars, starting_cash, f"momentum_{lookback}", desired)


def default_baselines(bars: list[Bar], starting_cash: float) -> dict[str, BenchmarkResult]:
    return {
        "buy_and_hold": buy_and_hold(bars, starting_cash),
        "sma_20_50": sma_crossover_baseline(bars, starting_cash, fast=20, slow=50),
        "momentum_20": momentum_baseline(bars, starting_cash, lookback=20),
    }


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def sharpe_significance(daily_returns_in: Iterable[float]) -> tuple[float, float]:
    """t-stat and two-sided p-value for H0: Sharpe == 0.

    Uses population standard deviation, the same convention as the ported test.
    """
    returns = [value for value in daily_returns_in if not math.isnan(value)]
    if len(returns) < 2 or _population_std_zero(returns):
        return 0.0, 1.0
    sharpe_annualized = population_sharpe(returns)
    se = math.sqrt(TRADING_DAYS_PER_YEAR / len(returns))
    t_stat = sharpe_annualized / se if se > 0 else 0.0
    p_value = 2 * (1 - _phi(abs(t_stat)))
    return float(t_stat), float(p_value)


def _population_std_zero(returns: list[float]) -> bool:
    mean = sum(returns) / len(returns)
    var = sum((value - mean) ** 2 for value in returns) / len(returns)
    return var == 0.0


@dataclass(frozen=True)
class WalkForwardSplit:
    train_start: str
    train_end: str
    test_start: str
    test_end: str


def walk_forward_splits(
    start: str,
    end: str,
    train_years: float = 3.0,
    test_years: float = 1.0,
    stride_years: float = 1.0,
) -> list[WalkForwardSplit]:
    """Rolling train then test windows. A split's test starts when its train ends."""
    cursor = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    splits: list[WalkForwardSplit] = []
    train_days = int(train_years * 365.25)
    test_days = int(test_years * 365.25)
    stride_days = int(stride_years * 365.25)
    while cursor + timedelta(days=train_days + test_days) <= end_dt:
        train_start = cursor
        train_end = cursor + timedelta(days=train_days)
        test_start = train_end
        test_end = train_end + timedelta(days=test_days)
        splits.append(
            WalkForwardSplit(
                train_start=train_start.strftime("%Y-%m-%d"),
                train_end=train_end.strftime("%Y-%m-%d"),
                test_start=test_start.strftime("%Y-%m-%d"),
                test_end=test_end.strftime("%Y-%m-%d"),
            )
        )
        cursor = cursor + timedelta(days=stride_days)
    return splits

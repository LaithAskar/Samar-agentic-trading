from __future__ import annotations

from datetime import date

from samar_data.market import FIXTURE_DIR, FixtureMarketData
from samar_engine.backtest.engine import BacktestEngine
from samar_engine.backtest.metrics import compute_metrics
from samar_engine.backtest.rigor import buy_and_hold, sharpe_significance
from samar_engine.dsl import compile_strategy, sma_cross_spec


def test_fixture_slice_is_frozen() -> None:
    data = FixtureMarketData()
    bars = data.bars("AAPL", date(2020, 1, 2), date(2020, 1, 6))
    assert [(bar.timestamp.date().isoformat(), round(bar.close, 4)) for bar in bars] == [
        ("2020-01-02", 99.1727),
        ("2020-01-03", 98.9105),
        ("2020-01-06", 96.824),
    ]
    assert (FIXTURE_DIR / "SPY.csv").exists()


def test_sma_cross_aapl_2020_2024_frozen_fixture() -> None:
    """The committed AAPL file is the seeded series, not a vendor download.

    SMA 20/50 returns -22.14%, CAGR -4.89%, win rate 33.33%, Sharpe -0.35.
    Buy-and-hold of the same bars is -46.32%.
    """
    bars = FixtureMarketData().bars("AAPL", date(2020, 1, 1), date(2024, 12, 31))
    result = BacktestEngine(starting_cash=100_000.0, slippage_bps=5.0).run(
        compile_strategy(sma_cross_spec("AAPL", fast=20, slow=50)),
        "AAPL",
        iter(bars),
    )
    metrics = compute_metrics(result.portfolio)
    benchmark = buy_and_hold(bars, starting_cash=100_000.0)
    returns = []
    equity = [point[1] for point in result.portfolio.equity_curve]
    for prev, cur in zip(equity, equity[1:], strict=False):
        returns.append(0.0 if prev == 0 else (cur / prev) - 1.0)
    _t_stat, p_value = sharpe_significance(returns)
    assert len(bars) == 1304
    assert metrics.num_round_trips == 12
    assert round(metrics.total_return_pct, 2) == -22.14
    assert round(metrics.cagr_pct, 2) == -4.89
    assert round(metrics.sharpe, 2) == -0.35
    assert round(metrics.win_rate_pct, 2) == 33.33
    assert round(p_value, 4) == 0.4215
    assert round(benchmark.total_return_pct, 2) == -46.32

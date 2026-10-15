from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from samar_engine.backtest.engine import DEFAULT_SLIPPAGE_BPS, BacktestEngine
from samar_engine.backtest.metrics import compute_metrics, sharpe_standard_error
from samar_engine.backtest.rigor import (
    buy_and_hold,
    default_baselines,
    momentum_baseline,
    sharpe_significance,
    sma_crossover_baseline,
    walk_forward_splits,
)
from samar_engine.core.events import Bar
from samar_engine.core.orders import Order, Side
from samar_engine.core.portfolio import Portfolio
from samar_engine.core.strategy import Strategy
from samar_engine.dsl import StrategySpec, compile_strategy, rsi_mean_rev_spec, sma_cross_spec
from samar_engine.reference_strategies import RsiMeanReversion, SmaCross


def make_bars(prices: list[tuple[float, float]], symbol: str = "TEST") -> list[Bar]:
    start = datetime(2024, 1, 1)
    return [
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(days=i),
            open=o,
            high=max(o, c),
            low=min(o, c),
            close=c,
            volume=1_000_000,
        )
        for i, (o, c) in enumerate(prices)
    ]


class BuyOnce(Strategy):
    name = "buy_once"

    def __init__(self, buy_on_bar_index: int, quantity: int) -> None:
        self.buy_on_bar_index = buy_on_bar_index
        self.quantity = quantity
        self._i = -1
        self.seen_bars: list[Bar] = []

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
        self._i += 1
        self.seen_bars.append(bar)
        if self._i == self.buy_on_bar_index:
            return [Order(symbol=bar.symbol, side=Side.BUY, quantity=self.quantity)]
        return []


def test_order_fills_at_next_bar_open_not_current_close() -> None:
    bars = make_bars([(10.0, 11.0), (12.0, 13.0), (14.0, 15.0)])
    strat = BuyOnce(buy_on_bar_index=0, quantity=10)
    engine = BacktestEngine(starting_cash=1000.0, slippage_bps=0.0)
    result = engine.run(strat, "TEST", iter(bars))
    fills = result.portfolio.fills
    assert len(fills) == 1
    fill = fills[0]
    assert fill.price == 12.0
    assert fill.timestamp == bars[1].timestamp


def test_default_slippage_is_five_bps() -> None:
    bars = make_bars([(10.0, 11.0), (12.0, 13.0)])
    strat = BuyOnce(buy_on_bar_index=0, quantity=1)
    result = BacktestEngine(starting_cash=1000.0).run(strat, "TEST", iter(bars))
    assert DEFAULT_SLIPPAGE_BPS == 5.0
    assert result.portfolio.fills[0].price == pytest.approx(12.0 * 1.0005)


def test_no_orders_filled_after_final_bar() -> None:
    bars = make_bars([(10.0, 11.0), (12.0, 13.0)])
    strat = BuyOnce(buy_on_bar_index=1, quantity=5)
    result = BacktestEngine(starting_cash=1000.0, slippage_bps=0.0).run(strat, "TEST", iter(bars))
    assert result.portfolio.fills == []


def test_equity_marked_to_close_not_open() -> None:
    bars = make_bars([(10.0, 11.0), (12.0, 20.0)])

    class BuyFirst(Strategy):
        name = "buy_first"

        def __init__(self) -> None:
            self._i = -1

        def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
            self._i += 1
            if self._i == 0:
                return [Order(symbol=bar.symbol, side=Side.BUY, quantity=10)]
            return []

    result = BacktestEngine(starting_cash=1000.0, slippage_bps=0.0).run(BuyFirst(), "TEST", iter(bars))
    final_equity = result.portfolio.equity_curve[-1][1]
    assert final_equity == pytest.approx(1080.0)


def test_insufficient_cash_order_rejected_silently() -> None:
    bars = make_bars([(10.0, 11.0), (12.0, 13.0)])
    strat = BuyOnce(buy_on_bar_index=0, quantity=10_000)
    result = BacktestEngine(starting_cash=100.0, slippage_bps=0.0).run(strat, "TEST", iter(bars))
    assert result.portfolio.fills == []
    assert result.portfolio.cash == 100.0


def test_strategy_never_sees_future_bars() -> None:
    bars = make_bars([(10, 11), (12, 13), (14, 15), (16, 17)])
    strat = BuyOnce(buy_on_bar_index=0, quantity=1)
    BacktestEngine(starting_cash=1000.0, slippage_bps=0.0).run(strat, "TEST", iter(bars))
    assert [seen.timestamp for seen in strat.seen_bars] == [bar.timestamp for bar in bars]


def test_slippage_buys_worse_sells_worse() -> None:
    bars = make_bars([(10.0, 11.0), (100.0, 100.0), (200.0, 200.0)])
    strat = BuyOnce(buy_on_bar_index=0, quantity=1)
    result = BacktestEngine(starting_cash=1000.0, slippage_bps=50.0).run(strat, "TEST", iter(bars))
    assert result.portfolio.fills[0].price == pytest.approx(100.0 * 1.005)


def test_commission_deducted_from_cash() -> None:
    bars = make_bars([(10.0, 11.0), (100.0, 100.0)])
    strat = BuyOnce(buy_on_bar_index=0, quantity=1)
    result = BacktestEngine(starting_cash=1000.0, slippage_bps=0.0, commission_per_trade=2.50).run(
        strat, "TEST", iter(bars)
    )
    assert result.portfolio.cash == pytest.approx(1000.0 - 100.0 - 2.50)


def test_engine_rejects_negative_friction() -> None:
    with pytest.raises(ValueError, match="slippage_bps"):
        BacktestEngine(slippage_bps=-1)
    with pytest.raises(ValueError, match="commission"):
        BacktestEngine(commission_per_trade=-1)


def test_portfolio_round_trip_pnl() -> None:
    pf = Portfolio(starting_cash=1000.0)
    pf.fill_at(Order("X", Side.BUY, 10), price=10.0, timestamp=datetime(2024, 1, 1))
    pf.fill_at(Order("X", Side.SELL, 10), price=12.0, timestamp=datetime(2024, 1, 2))
    assert pf.cash == pytest.approx(1020.0)
    assert pf.position("X") == 0.0


class BuyThenSell(Strategy):
    name = "buy_then_sell"

    def __init__(self) -> None:
        self._i = -1

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
        self._i += 1
        if self._i == 0:
            return [Order(symbol=bar.symbol, side=Side.BUY, quantity=10)]
        if self._i == 2:
            return [Order(symbol=bar.symbol, side=Side.SELL, quantity=10)]
        return []


def test_research_metrics_include_volatility_profit_factor_and_exposure() -> None:
    bars = make_bars([(10, 10), (10, 12), (12, 14), (14, 16), (16, 16)])
    result = BacktestEngine(starting_cash=1000.0, slippage_bps=0.0).run(BuyThenSell(), "TEST", iter(bars))
    metrics = compute_metrics(result.portfolio)
    assert metrics.ending_equity == pytest.approx(1040.0)
    assert metrics.exposure_pct == pytest.approx(40.0)
    assert metrics.num_round_trips == 1
    assert metrics.win_rate_pct == pytest.approx(100.0)
    assert metrics.profit_factor == float("inf")
    assert metrics.sharpe == pytest.approx(13.746379598749618)
    assert metrics.sharpe_se == pytest.approx(4.885731164228642)
    assert metrics.volatility_pct == pytest.approx(18.152373137389787)


def test_sharpe_se_matches_mertens_lo_on_known_returns() -> None:
    returns = [0.01, -0.02, 0.015, 0.005]
    se = sharpe_standard_error(returns)
    assert se == pytest.approx(1.0318212889903915)


def test_default_baselines_are_deterministic_and_named() -> None:
    bars = make_bars([(10 + i, 10 + i) for i in range(80)])
    baselines = default_baselines(bars, starting_cash=1000.0)
    assert set(baselines) == {"buy_and_hold", "sma_20_50", "momentum_20"}
    assert baselines["buy_and_hold"].name == "buy_and_hold"
    assert baselines["buy_and_hold"].exposure_pct == pytest.approx(100.0)
    assert baselines["sma_20_50"].name == "sma_20_50"
    assert baselines["momentum_20"].name == "momentum_20"


def test_small_parameter_baselines_can_enter_market() -> None:
    bars = make_bars([(10 + i, 10 + i) for i in range(10)])
    sma = sma_crossover_baseline(bars, starting_cash=1000.0, fast=2, slow=3)
    mom = momentum_baseline(bars, starting_cash=1000.0, lookback=2)
    assert sma.exposure_pct == pytest.approx(70.0)
    assert mom.exposure_pct == pytest.approx(70.0)


def test_buy_and_hold_fills_at_second_bar_open() -> None:
    bars = make_bars([(10, 11), (12, 14), (15, 18), (16, 20)])
    result = buy_and_hold(bars, starting_cash=100.0)
    assert result.end_equity == pytest.approx(164.0)
    assert result.total_return_pct == pytest.approx(41.37931034482758)


def test_buy_and_hold_empty_returns_starting_cash() -> None:
    result = buy_and_hold([], starting_cash=100.0)
    assert result.end_equity == 100.0
    assert result.total_return_pct == 0.0


def test_sharpe_significance_zero_returns() -> None:
    t_stat, p_value = sharpe_significance([0.0, 0.0, 0.0, 0.0])
    assert t_stat == 0.0
    assert p_value == 1.0


def test_sharpe_significance_known_sample() -> None:
    returns = [0.001 + (i % 3 - 1) * 1e-5 for i in range(100)]
    t_stat, p_value = sharpe_significance(returns)
    assert t_stat == pytest.approx(1221.6634464346846)
    assert p_value == pytest.approx(0.0)


def test_walk_forward_first_split_dates() -> None:
    splits = walk_forward_splits("2018-01-01", "2024-12-31", train_years=3.0, test_years=1.0)
    assert len(splits) == 4
    assert splits[0].train_start == "2018-01-01"
    assert splits[0].train_end == "2020-12-31"
    assert splits[0].test_start == "2020-12-31"
    assert splits[0].test_end == "2021-12-31"


def test_walk_forward_returns_empty_when_window_too_small() -> None:
    splits = walk_forward_splits("2024-01-01", "2024-06-01", train_years=3.0, test_years=1.0)
    assert splits == []


def test_dsl_sma_matches_python_class_trades() -> None:
    bars = make_bars([(10 + (i % 7), 10 + ((i * 3) % 11)) for i in range(80)], symbol="AAPL")
    engine = BacktestEngine(starting_cash=10_000.0, slippage_bps=5.0)
    python_result = engine.run(SmaCross(fast=5, slow=12), "AAPL", iter(bars))
    dsl_result = engine.run(compile_strategy(sma_cross_spec("AAPL", fast=5, slow=12)), "AAPL", iter(bars))
    assert [(f.side, f.quantity, f.price, f.timestamp) for f in dsl_result.portfolio.fills] == [
        (f.side, f.quantity, f.price, f.timestamp) for f in python_result.portfolio.fills
    ]


def test_dsl_rsi_matches_python_class_trades() -> None:
    prices = []
    close = 50.0
    for i in range(60):
        close += -2.5 if i % 9 < 4 else 2.0
        prices.append((close - 0.4, close))
    bars = make_bars(prices, symbol="AAPL")
    engine = BacktestEngine(starting_cash=10_000.0, slippage_bps=0.0)
    python_result = engine.run(RsiMeanReversion(period=5, oversold=35, overbought=65), "AAPL", iter(bars))
    spec = rsi_mean_rev_spec("AAPL", period=5, oversold=35, overbought=65)
    dsl_result = engine.run(compile_strategy(spec), "AAPL", iter(bars))
    assert [(f.side, f.quantity, f.price) for f in dsl_result.portfolio.fills] == [
        (f.side, f.quantity, f.price) for f in python_result.portfolio.fills
    ]
    assert len(python_result.portfolio.fills) == 11
    first = python_result.portfolio.fills[0]
    assert (first.side.value, first.quantity, first.price) == ("BUY", 232, 39.6)


def test_invalid_dsl_reports_the_field() -> None:
    with pytest.raises(ValidationError) as bad_period:
        StrategySpec.model_validate(
            {
                "name": "bad",
                "universe": ["AAPL"],
                "rules": [
                    {
                        "when": {
                            "kind": "compare",
                            "left": {"kind": "indicator", "name": "sma", "ticker": "AAPL"},
                            "op": "<",
                            "right": {"kind": "const", "value": 1},
                        },
                        "then": {
                            "kind": "buy",
                            "ticker": "AAPL",
                            "amount": {"kind": "shares", "value": 1},
                        },
                    }
                ],
            }
        )
    locations = [tuple(err["loc"]) for err in bad_period.value.errors()]
    assert ("rules", 0, "when", "compare", "left", "indicator") in locations

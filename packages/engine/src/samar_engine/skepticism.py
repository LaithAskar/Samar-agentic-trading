from __future__ import annotations

from pydantic import BaseModel

from samar_engine.backtest.metrics import Metrics
from samar_engine.backtest.rigor import BenchmarkResult


class Skepticism(BaseModel):
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


def build_skepticism(
    metrics: Metrics,
    benchmark: BenchmarkResult,
    sharpe_p_value: float,
    sample_days: int,
) -> Skepticism:
    beat = metrics.total_return_pct > benchmark.total_return_pct
    warnings: list[str] = []
    if not beat:
        warnings.append("The strategy lost to buy-and-hold over this window.")
    if sample_days < 252:
        warnings.append("The sample is shorter than one trading year.")
    if metrics.num_round_trips < 10:
        warnings.append("Fewer than 10 round trips. The win rate is noisy.")
    if sharpe_p_value > 0.05:
        warnings.append("The Sharpe ratio is not distinguishable from zero at 5%.")
    return Skepticism(
        beat_benchmark=beat,
        benchmark_name=benchmark.name,
        strategy_return_pct=metrics.total_return_pct,
        benchmark_return_pct=benchmark.total_return_pct,
        sharpe=metrics.sharpe,
        sharpe_se=metrics.sharpe_se,
        sharpe_p_value=sharpe_p_value,
        num_round_trips=metrics.num_round_trips,
        sample_days=sample_days,
        warnings=warnings,
    )

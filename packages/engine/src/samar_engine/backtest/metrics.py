from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import pstdev, stdev

from samar_engine.core.orders import Side
from samar_engine.core.portfolio import Portfolio

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class Metrics:
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sharpe_se: float
    volatility_pct: float
    max_drawdown_pct: float
    exposure_pct: float
    num_fills: int
    num_round_trips: int
    win_rate_pct: float
    profit_factor: float


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(stdev(values))


def _population_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(pstdev(values))


def daily_returns(equity: list[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in zip(equity, equity[1:], strict=False):
        if prev == 0:
            out.append(0.0)
        else:
            out.append((cur / prev) - 1.0)
    return out


def sharpe_ratio(returns: list[float]) -> float:
    """Annualized Sharpe using the sample standard deviation (ddof=1)."""
    if len(returns) < 2:
        return 0.0
    sigma = _sample_std(returns)
    if sigma == 0.0:
        return 0.0
    mean = sum(returns) / len(returns)
    return mean / sigma * math.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_standard_error(returns: list[float]) -> float:
    """Mertens / Lo (2002) SE of the annualized Sharpe. nan when n < 2."""
    n = len(returns)
    if n < 2:
        return float("nan")
    sr = sharpe_ratio(returns)
    return math.sqrt((1.0 + (sr**2) / 2.0) / n)


def _round_trip_pnls(portfolio: Portfolio) -> list[float]:
    lots_by_symbol: dict[str, list[tuple[float, float]]] = {}
    pnls: list[float] = []
    for fill in portfolio.fills:
        lots = lots_by_symbol.setdefault(fill.symbol, [])
        if fill.side is Side.BUY:
            lots.append((fill.quantity, fill.price))
            continue
        remaining = fill.quantity
        while remaining > 1e-9 and lots:
            lot_qty, lot_price = lots[0]
            take = min(lot_qty, remaining)
            pnls.append((fill.price - lot_price) * take)
            if take >= lot_qty - 1e-9:
                lots.pop(0)
            else:
                lots[0] = (lot_qty - take, lot_price)
            remaining -= take
    return pnls


def _exposure_pct(portfolio: Portfolio) -> float:
    timestamps = [ts for ts, _equity in portfolio.equity_curve]
    if not timestamps:
        return 0.0
    fills = sorted(portfolio.fills, key=lambda fill: fill.timestamp)
    positions: dict[str, float] = {}
    fill_i = 0
    exposed = 0
    for ts in timestamps:
        while fill_i < len(fills) and fills[fill_i].timestamp <= ts:
            fill = fills[fill_i]
            positions[fill.symbol] = positions.get(fill.symbol, 0.0) + fill.signed_quantity
            if abs(positions[fill.symbol]) < 1e-9:
                del positions[fill.symbol]
            fill_i += 1
        if positions:
            exposed += 1
    return exposed / len(timestamps) * 100.0


def _empty(portfolio: Portfolio) -> Metrics:
    return Metrics(
        starting_equity=portfolio.starting_cash,
        ending_equity=portfolio.starting_cash,
        total_return_pct=0.0,
        cagr_pct=0.0,
        sharpe=0.0,
        sharpe_se=float("nan"),
        volatility_pct=0.0,
        max_drawdown_pct=0.0,
        exposure_pct=0.0,
        num_fills=len(portfolio.fills),
        num_round_trips=0,
        win_rate_pct=0.0,
        profit_factor=0.0,
    )


def compute_metrics(portfolio: Portfolio) -> Metrics:
    curve = portfolio.equity_curve
    if len(curve) < 2:
        return _empty(portfolio)

    equity = [point[1] for point in curve]
    starting = equity[0]
    ending = equity[-1]
    total_return = (ending / starting) - 1.0 if starting else 0.0
    days = (curve[-1][0] - curve[0][0]).days
    years = max(days / 365.25, 1e-9)
    cagr = (ending / starting) ** (1 / years) - 1.0 if starting > 0 else 0.0

    rets = daily_returns(equity)
    sigma = _sample_std(rets)
    if sigma > 0:
        sharpe = sharpe_ratio(rets)
        volatility = sigma * math.sqrt(TRADING_DAYS_PER_YEAR)
    else:
        sharpe = 0.0
        volatility = 0.0

    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, (value / peak) - 1.0)

    pnls = _round_trip_pnls(portfolio)
    wins = sum(1 for pnl in pnls if pnl > 0)
    win_rate = (wins / len(pnls) * 100) if pnls else 0.0
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = math.inf
    else:
        profit_factor = 0.0

    return Metrics(
        starting_equity=starting,
        ending_equity=ending,
        total_return_pct=total_return * 100,
        cagr_pct=cagr * 100,
        sharpe=sharpe,
        sharpe_se=sharpe_standard_error(rets),
        volatility_pct=volatility * 100,
        max_drawdown_pct=max_dd * 100,
        exposure_pct=_exposure_pct(portfolio),
        num_fills=len(portfolio.fills),
        num_round_trips=len(pnls),
        win_rate_pct=win_rate,
        profit_factor=profit_factor,
    )


def population_sharpe(returns: list[float]) -> float:
    """Annualized Sharpe with population std, matching the ported t-test."""
    if len(returns) < 2:
        return 0.0
    sigma = _population_std(returns)
    if sigma == 0.0:
        return 0.0
    mean = sum(returns) / len(returns)
    return mean / sigma * math.sqrt(TRADING_DAYS_PER_YEAR)

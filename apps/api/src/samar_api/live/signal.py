from __future__ import annotations

from samar_engine.core.events import Bar
from samar_engine.core.portfolio import Portfolio
from samar_engine.dsl import StrategySpec, compile_strategy

from samar_api.live.types import Limits, OrderIntent


def strategy_intent(
    spec: StrategySpec,
    bars: list[Bar],
    quote: float,
    limits: Limits,
    held: float,
) -> OrderIntent | None:
    if quote <= 0 or not bars:
        return None
    strategy = compile_strategy(spec)
    portfolio = Portfolio(starting_cash=limits.capital_cap)
    latest: OrderIntent | None = None
    for bar in bars:
        orders = strategy.on_bar(bar, portfolio)
        if not orders:
            continue
        order = orders[-1]
        room = int(limits.max_order_dollars // quote)
        if order.side.value == "BUY":
            if held > 0 or room < 1:
                latest = None
                continue
            quantity = min(int(order.quantity), room)
            if quantity < 1:
                latest = None
                continue
            latest = OrderIntent(
                symbol=order.symbol,
                side="BUY",
                quantity=quantity,
                limit_price=quote,
                reason=f"{spec.name} wants {int(order.quantity)} shares, sized to the per-order cap",
                model=f"strategy:{spec.name}",
            )
            continue
        if held <= 0:
            latest = None
            continue
        quantity = min(int(held), int(order.quantity))
        if quantity < 1:
            latest = None
            continue
        latest = OrderIntent(
            symbol=order.symbol,
            side="SELL",
            quantity=quantity,
            limit_price=quote,
            reason=f"{spec.name} wants to sell {quantity} shares",
            model=f"strategy:{spec.name}",
        )
    return latest

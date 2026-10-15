from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from samar_engine.core.events import Bar
from samar_engine.core.orders import Order, Side
from samar_engine.core.portfolio import Portfolio
from samar_engine.core.strategy import Strategy
from samar_engine.indicators import Ema, Price, Rsi, Sma

IndicatorName = Literal["sma", "ema", "rsi", "price"]
CompareOp = Literal["<", ">", "crosses_above", "crosses_below"]
AmountKind = Literal["pct_cash", "pct_position", "shares"]


class IndicatorOperand(BaseModel):
    kind: Literal["indicator"] = "indicator"
    name: IndicatorName
    ticker: str
    period: int | None = None

    @model_validator(mode="after")
    def period_matches_indicator(self) -> IndicatorOperand:
        if self.name == "price":
            if self.period is not None:
                raise ValueError("price has no period")
            return self
        if self.period is None or self.period < 2:
            raise ValueError(f"{self.name} requires period >= 2")
        return self


class ConstOperand(BaseModel):
    kind: Literal["const"] = "const"
    value: float


Operand = Annotated[IndicatorOperand | ConstOperand, Field(discriminator="kind")]


class CompareCondition(BaseModel):
    kind: Literal["compare"] = "compare"
    left: Operand
    op: CompareOp
    right: Operand


class AllCondition(BaseModel):
    kind: Literal["all"] = "all"
    of: list[Condition]


class AnyCondition(BaseModel):
    kind: Literal["any"] = "any"
    of: list[Condition]


Condition = Annotated[
    CompareCondition | AllCondition | AnyCondition,
    Field(discriminator="kind"),
]
AllCondition.model_rebuild()
AnyCondition.model_rebuild()


class Amount(BaseModel):
    kind: AmountKind
    value: float

    @model_validator(mode="after")
    def value_is_usable(self) -> Amount:
        if self.value <= 0:
            raise ValueError("amount must be positive")
        if self.kind in {"pct_cash", "pct_position"} and self.value > 100:
            raise ValueError("percent amount cannot exceed 100")
        return self


class Action(BaseModel):
    kind: Literal["buy", "sell"]
    ticker: str
    amount: Amount


class Rule(BaseModel):
    when: Condition
    then: Action


class Sizing(BaseModel):
    buffer_pct: float = 0.01

    @model_validator(mode="after")
    def buffer_range(self) -> Sizing:
        if not 0.0 <= self.buffer_pct < 1.0:
            raise ValueError("buffer_pct must be in [0, 1)")
        return self


class StrategySpec(BaseModel):
    name: str
    universe: list[str]
    rules: list[Rule]
    sizing: Sizing = Field(default_factory=Sizing)

    @model_validator(mode="after")
    def one_ticker_mvp(self) -> StrategySpec:
        if len(self.universe) != 1:
            raise ValueError("MVP strategies use exactly one ticker")
        if not self.name.strip():
            raise ValueError("name is required")
        ticker = self.universe[0]
        for rule in self.rules:
            if rule.then.ticker != ticker:
                raise ValueError("action ticker must match the universe")
        return self


def sma_cross_spec(ticker: str = "AAPL", fast: int = 20, slow: int = 50) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "sma_cross",
            "universe": [ticker],
            "sizing": {"buffer_pct": 0.01},
            "rules": [
                {
                    "when": {
                        "kind": "compare",
                        "left": {"kind": "indicator", "name": "sma", "ticker": ticker, "period": fast},
                        "op": "crosses_above",
                        "right": {
                            "kind": "indicator",
                            "name": "sma",
                            "ticker": ticker,
                            "period": slow,
                        },
                    },
                    "then": {
                        "kind": "buy",
                        "ticker": ticker,
                        "amount": {"kind": "pct_cash", "value": 100},
                    },
                },
                {
                    "when": {
                        "kind": "compare",
                        "left": {"kind": "indicator", "name": "sma", "ticker": ticker, "period": fast},
                        "op": "crosses_below",
                        "right": {
                            "kind": "indicator",
                            "name": "sma",
                            "ticker": ticker,
                            "period": slow,
                        },
                    },
                    "then": {
                        "kind": "sell",
                        "ticker": ticker,
                        "amount": {"kind": "pct_position", "value": 100},
                    },
                },
            ],
        }
    )


def rsi_mean_rev_spec(
    ticker: str = "AAPL",
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "rsi_mean_rev",
            "universe": [ticker],
            "sizing": {"buffer_pct": 0.01},
            "rules": [
                {
                    "when": {
                        "kind": "compare",
                        "left": {
                            "kind": "indicator",
                            "name": "rsi",
                            "ticker": ticker,
                            "period": period,
                        },
                        "op": "crosses_below",
                        "right": {"kind": "const", "value": oversold},
                    },
                    "then": {
                        "kind": "buy",
                        "ticker": ticker,
                        "amount": {"kind": "pct_cash", "value": 100},
                    },
                },
                {
                    "when": {
                        "kind": "compare",
                        "left": {
                            "kind": "indicator",
                            "name": "rsi",
                            "ticker": ticker,
                            "period": period,
                        },
                        "op": "crosses_above",
                        "right": {"kind": "const", "value": overbought},
                    },
                    "then": {
                        "kind": "sell",
                        "ticker": ticker,
                        "amount": {"kind": "pct_position", "value": 100},
                    },
                },
            ],
        }
    )


class _Series:
    def __init__(self, operand: IndicatorOperand) -> None:
        self.operand = operand
        period = operand.period
        if operand.name == "sma":
            if period is None:
                raise ValueError("sma requires a period")
            self._inner: Sma | Ema | Rsi | Price = Sma(period)
        elif operand.name == "ema":
            if period is None:
                raise ValueError("ema requires a period")
            self._inner = Ema(period)
        elif operand.name == "rsi":
            if period is None:
                raise ValueError("rsi requires a period")
            self._inner = Rsi(period)
        else:
            self._inner = Price()
        self.value: float | None = None
        self.prev: float | None = None

    def update(self, close: float) -> None:
        self.prev = self.value
        self.value = self._inner.update(close)


def _operand_key(operand: Operand) -> str:
    if isinstance(operand, ConstOperand):
        return f"const:{operand.value}"
    period = "none" if operand.period is None else str(operand.period)
    return f"{operand.name}:{operand.ticker}:{period}"


class CompiledStrategy(Strategy):
    def __init__(self, spec: StrategySpec) -> None:
        self.spec = spec
        self.name = spec.name
        self._series: dict[str, _Series] = {}
        self._collect(spec.rules)

    def _collect(self, rules: list[Rule]) -> None:
        for rule in rules:
            self._walk(rule.when)

    def _walk(self, condition: Condition) -> None:
        if isinstance(condition, CompareCondition):
            for operand in (condition.left, condition.right):
                if isinstance(operand, IndicatorOperand):
                    key = _operand_key(operand)
                    self._series.setdefault(key, _Series(operand))
            return
        for child in condition.of:
            self._walk(child)

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> list[Order]:
        for series in self._series.values():
            if series.operand.ticker == bar.symbol:
                series.update(bar.close)
        orders: list[Order] = []
        for rule in self.spec.rules:
            if rule.then.ticker != bar.symbol:
                continue
            if not self._holds(rule.when):
                continue
            order = self._order(rule.then, bar, portfolio)
            if order is not None:
                orders.append(order)
                if order.side is Side.BUY:
                    break
                break
        return orders

    def _holds(self, condition: Condition) -> bool:
        if isinstance(condition, AllCondition):
            return all(self._holds(child) for child in condition.of)
        if isinstance(condition, AnyCondition):
            return any(self._holds(child) for child in condition.of)
        return self._compare(condition)

    def _read(self, operand: Operand) -> tuple[float | None, float | None]:
        if isinstance(operand, ConstOperand):
            return operand.value, operand.value
        series = self._series[_operand_key(operand)]
        return series.value, series.prev

    def _compare(self, condition: CompareCondition) -> bool:
        left, prev_left = self._read(condition.left)
        right, prev_right = self._read(condition.right)
        if left is None or right is None:
            return False
        if condition.op == "<":
            return left < right
        if condition.op == ">":
            return left > right
        if prev_left is None or prev_right is None:
            return False
        if condition.op == "crosses_above":
            return prev_left <= prev_right and left > right
        return prev_left >= prev_right and left < right

    def _order(self, action: Action, bar: Bar, portfolio: Portfolio) -> Order | None:
        held = portfolio.position(bar.symbol)
        if action.kind == "buy":
            if held != 0:
                return None
            if action.amount.kind == "shares":
                qty = int(action.amount.value)
            elif action.amount.kind == "pct_cash":
                budget = portfolio.cash * (action.amount.value / 100.0)
                buffered = budget * (1.0 - self.spec.sizing.buffer_pct)
                qty = int(buffered // bar.close) if bar.close > 0 else 0
            else:
                return None
            if qty <= 0:
                return None
            return Order(symbol=bar.symbol, side=Side.BUY, quantity=qty)
        if held <= 0:
            return None
        if action.amount.kind == "shares":
            qty = min(held, action.amount.value)
        elif action.amount.kind == "pct_position":
            qty = held * (action.amount.value / 100.0)
        else:
            return None
        if qty <= 0:
            return None
        return Order(symbol=bar.symbol, side=Side.SELL, quantity=qty)


def compile_strategy(spec: StrategySpec) -> CompiledStrategy:
    return CompiledStrategy(spec)

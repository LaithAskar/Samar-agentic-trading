from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from samar_api.live.types import GuardContext, GuardResult, Held, OrderIntent

NY = ZoneInfo("America/New_York")
ALLOWLIST = frozenset(
    {
        "SPY",
        "QQQ",
        "IWM",
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "TSLA",
        "AMD",
        "AVGO",
        "JPM",
        "XOM",
        "BAC",
        "F",
        "INTC",
        "PFE",
        "T",
        "KO",
        "WMT",
        "DIS",
        "CSCO",
        "PYPL",
        "SOFI",
        "PLTR",
    }
)
_CRYPTO = frozenset({"BTC", "ETH", "DOGE"})
ENABLE_PHRASE = "I understand I can lose this money"
AUTO_PHRASE = "auto trade while I am away"
TICKET_MINUTES = 5
REJECT_LIMIT = 3
STALE_DAYS = 4


def sell_proceeds_unsettled(sold_at: datetime, now: datetime) -> bool:
    """A stock sale in a cash account settles the next business day."""
    if sold_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = sold_at.astimezone(NY)
    day = local.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    settles = datetime(day.year, day.month, day.day, tzinfo=NY)
    return now < settles


def bars_current(last_bar: datetime, now: datetime) -> bool:
    """Daily bars are current when the last one is within a long weekend of today in New York."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    age = now.astimezone(NY).date() - last_bar.date()
    return age.days <= STALE_DAYS


def market_open(now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(NY)
    if local.weekday() >= 5:
        return False
    opened = local.replace(hour=9, minute=30, second=0, microsecond=0)
    closed = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return opened <= local < closed


def whole_shares(value: object) -> int:
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, int) or value < 1:
        raise ValueError("quantity must be a whole share")
    return value


def evaluate(intent: OrderIntent, ctx: GuardContext) -> GuardResult:
    symbol = intent.symbol.strip().upper()
    held = _held(ctx.positions, symbol)
    for result in (
        _disabled(ctx),
        _margin(intent),
        _instrument(intent.symbol, symbol, ctx.allowlist),
        _shares(intent.quantity),
        _price(intent.limit_price),
        _short(intent, held),
        _session(ctx.now),
        _dollars(intent, ctx),
        _pace(ctx),
        _loss(ctx),
    ):
        if result is not None:
            return result
    return GuardResult(ok=True, reason="", halt=False)


def _disabled(ctx: GuardContext) -> GuardResult | None:
    if ctx.live_enabled:
        return None
    return GuardResult(ok=False, reason="live mode is off", halt=False)


def _margin(intent: OrderIntent) -> GuardResult | None:
    if not intent.use_margin:
        return None
    return GuardResult(ok=False, reason="margin is not allowed", halt=False)


def _instrument(raw: str, symbol: str, allowlist: frozenset[str]) -> GuardResult | None:
    if " " in raw or len(symbol) > 8:
        return GuardResult(ok=False, reason="options are not allowed", halt=False)
    if "-" in symbol or symbol.endswith("USD") or symbol in _CRYPTO:
        return GuardResult(ok=False, reason="crypto is not allowed", halt=False)
    if symbol not in allowlist:
        return GuardResult(ok=False, reason="symbol is not on the allowlist", halt=False)
    return None


def _shares(quantity: int) -> GuardResult | None:
    if quantity >= 1:
        return None
    return GuardResult(ok=False, reason="quantity must be a whole share", halt=False)


def _price(limit_price: float) -> GuardResult | None:
    if limit_price > 0:
        return None
    return GuardResult(ok=False, reason="limit price is required", halt=False)


def _short(intent: OrderIntent, held: float) -> GuardResult | None:
    if intent.side == "SELL" and intent.quantity > held:
        return GuardResult(ok=False, reason="shorting is not allowed", halt=False)
    return None


def _session(now: datetime) -> GuardResult | None:
    if market_open(now):
        return None
    return GuardResult(ok=False, reason="market is closed", halt=False)


def _dollars(intent: OrderIntent, ctx: GuardContext) -> GuardResult | None:
    if intent.side != "BUY":
        return None
    notional = intent.quantity * intent.limit_price
    if notional > ctx.limits.max_order_dollars:
        return GuardResult(ok=False, reason="order exceeds the per-order cap", halt=False)
    held_value = 0.0
    for position in ctx.positions:
        if position.market_value is None:
            return GuardResult(ok=False, reason="position value is unknown", halt=False)
        held_value += position.market_value
    if held_value + ctx.open_buys + notional > ctx.limits.capital_cap:
        return GuardResult(ok=False, reason="order exceeds the capital cap", halt=False)
    settled = ctx.buying_power if ctx.settled_cash is None else ctx.settled_cash
    if notional > settled and settled < ctx.buying_power:
        return GuardResult(ok=False, reason="order exceeds settled cash", halt=False)
    if notional > ctx.buying_power:
        return GuardResult(ok=False, reason="order exceeds buying power", halt=False)
    return None


def _pace(ctx: GuardContext) -> GuardResult | None:
    day_cap = ctx.limits.max_orders_per_day
    if day_cap is not None and ctx.orders_today >= day_cap:
        return GuardResult(ok=False, reason="daily order limit reached", halt=False)
    if ctx.orders_last_minute >= ctx.limits.max_orders_per_minute:
        return GuardResult(ok=False, reason="model order rate limit reached", halt=False)
    return None


def _loss(ctx: GuardContext) -> GuardResult | None:
    if ctx.day_pnl > -ctx.limits.daily_loss_stop:
        return None
    return GuardResult(ok=False, reason="daily loss stop is hit", halt=True)


def _held(positions: tuple[Held, ...], symbol: str) -> float:
    for position in positions:
        if position.symbol.upper() == symbol:
            return position.quantity
    return 0.0

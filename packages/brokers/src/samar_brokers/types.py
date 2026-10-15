from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Account(BaseModel):
    account_id: str
    nickname: str


class Position(BaseModel):
    symbol: str
    quantity: float
    market_value: float


class PortfolioSnapshot(BaseModel):
    account_id: str
    equity: float
    cash: float
    positions: list[Position]


class Quote(BaseModel):
    symbol: str
    last: float


class BrokerPort(Protocol):
    """Read-only brokerage surface. Order methods are not part of this type."""

    def list_accounts(self) -> list[Account]:
        """Accounts the key can see."""
        ...

    def get_portfolio(self, account_id: str) -> PortfolioSnapshot:
        """Positions and balances. No orders are sent."""
        ...

    def get_quotes(self, account_id: str, symbols: list[str]) -> list[Quote]:
        """Personal-use quotes for this user's own key."""
        ...

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class Market(str, Enum):
    US = "US"
    HK = "HK"


class SecurityType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    WARRANT = "warrant"
    CBBC = "cbbc"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: Market
    security_type: SecurityType
    name: str = ""
    theme: str = ""
    last_trade_date: datetime | None = None


@dataclass(frozen=True)
class Quote:
    instrument: Instrument
    bid: float
    ask: float
    last: float
    timestamp: datetime

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread_bps(self) -> float:
        if self.mid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.mid * 10_000


@dataclass(frozen=True)
class Holding:
    instrument: Instrument
    quantity: float
    market_value_usd: float


@dataclass(frozen=True)
class Cash:
    available_usd: float


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: Cash
    holdings: tuple[Holding, ...] = ()
    broker_sync_ok: bool = True
    daily_realized_pnl_usd: float = 0.0

    def market_value_by_symbol(self, symbol: str) -> float:
        return sum(h.market_value_usd for h in self.holdings if h.instrument.symbol == symbol)

    def market_value_by_theme(self, theme: str) -> float:
        if not theme:
            return 0.0
        return sum(h.market_value_usd for h in self.holdings if h.instrument.theme == theme)


@dataclass(frozen=True)
class OrderDraft:
    instrument: Instrument
    side: Side
    quantity: float
    limit_price: float
    order_type: OrderType = OrderType.LIMIT
    reason: str = ""
    failure_plan: str = ""
    validity_seconds: int = 60
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    order_intent_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def notional(self) -> float:
        return abs(self.quantity * self.limit_price)


@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    reasons: tuple[str, ...] = ()


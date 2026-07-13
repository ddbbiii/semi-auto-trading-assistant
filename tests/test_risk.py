from __future__ import annotations

from datetime import datetime, timezone
import unittest

from trading_assistant.config import RiskConfig
from trading_assistant.domain import (
    Cash,
    Instrument,
    Market,
    PortfolioSnapshot,
    Quote,
    SecurityType,
    Side,
)
from trading_assistant.drafts import create_limit_draft
from trading_assistant.risk import RiskEngine


class RiskEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.instrument = Instrument(
            symbol="SPY",
            market=Market.US,
            security_type=SecurityType.ETF,
            theme="ai_semiconductor_storage",
        )
        self.quote = Quote(
            instrument=self.instrument,
            bid=580.0,
            ask=580.5,
            last=580.2,
            timestamp=datetime.now(timezone.utc),
        )

    def test_allows_small_limit_order(self) -> None:
        engine = RiskEngine(RiskConfig())
        draft = create_limit_draft(
            self.instrument,
            side=Side.BUY,
            quantity=1,
            limit_price=575,
            reason="test",
            failure_plan="test",
        )
        portfolio = PortfolioSnapshot(cash=Cash(available_usd=3000))
        result = engine.check(draft, self.quote, portfolio)
        self.assertTrue(result.allowed, result.reasons)

    def test_blocks_wide_spread(self) -> None:
        engine = RiskEngine(RiskConfig(max_spread_bps=10))
        quote = Quote(
            instrument=self.instrument,
            bid=570,
            ask=590,
            last=580,
            timestamp=datetime.now(timezone.utc),
        )
        draft = create_limit_draft(
            self.instrument,
            side=Side.BUY,
            quantity=1,
            limit_price=575,
            reason="test",
            failure_plan="test",
        )
        portfolio = PortfolioSnapshot(cash=Cash(available_usd=3000))
        result = engine.check(draft, quote, portfolio)
        self.assertFalse(result.allowed)
        self.assertTrue(any("Spread too wide" in reason for reason in result.reasons))

    def test_blocks_low_cash_after_buy(self) -> None:
        engine = RiskEngine(RiskConfig(min_cash_after_order_usd=500))
        draft = create_limit_draft(
            self.instrument,
            side=Side.BUY,
            quantity=5,
            limit_price=575,
            reason="test",
            failure_plan="test",
        )
        portfolio = PortfolioSnapshot(cash=Cash(available_usd=3000))
        result = engine.check(draft, self.quote, portfolio)
        self.assertFalse(result.allowed)
        self.assertTrue(any("single-order cap" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()

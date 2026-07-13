from __future__ import annotations

from datetime import datetime, timezone

from .config import RiskConfig
from .domain import OrderDraft, PortfolioSnapshot, Quote, RiskResult, SecurityType, Side


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def check(
        self,
        draft: OrderDraft,
        quote: Quote,
        portfolio: PortfolioSnapshot,
        *,
        now: datetime | None = None,
    ) -> RiskResult:
        now = now or datetime.now(timezone.utc)
        reasons: list[str] = []

        if draft.order_type.value != "limit":
            reasons.append("Only limit orders are allowed.")

        if not portfolio.broker_sync_ok:
            reasons.append("Local portfolio and broker state are not synchronized.")

        if portfolio.daily_realized_pnl_usd <= -abs(self.config.max_daily_loss_usd):
            reasons.append("Max daily loss reached; new orders are disabled.")

        quote_age = (now - quote.timestamp).total_seconds()
        if quote_age > self.config.max_quote_age_seconds:
            reasons.append(f"Quote is stale: {quote_age:.1f}s old.")

        if quote.spread_bps > self.config.max_spread_bps:
            reasons.append(f"Spread too wide: {quote.spread_bps:.1f} bps.")

        if draft.notional > self.config.single_order_max_usd:
            reasons.append(f"Order notional {draft.notional:.2f} exceeds single-order cap.")

        if draft.side == Side.BUY:
            cash_after = portfolio.cash.available_usd - draft.notional
            if cash_after < self.config.min_cash_after_order_usd:
                reasons.append(f"Cash after order {cash_after:.2f} below minimum reserve.")

            symbol_after = portfolio.market_value_by_symbol(draft.instrument.symbol) + draft.notional
            if symbol_after > self.config.single_symbol_max_usd:
                reasons.append(f"Symbol exposure {symbol_after:.2f} exceeds cap.")

            theme_after = portfolio.market_value_by_theme(draft.instrument.theme) + draft.notional
            if draft.instrument.theme and theme_after > self.config.theme_exposure_max_usd:
                reasons.append(f"Theme exposure {theme_after:.2f} exceeds cap.")

            if draft.instrument.security_type in {SecurityType.WARRANT, SecurityType.CBBC}:
                if draft.instrument.last_trade_date is None:
                    reasons.append("Warrant/CBBC last trade date is missing.")
                else:
                    days_left = (draft.instrument.last_trade_date.date() - now.date()).days
                    if days_left <= self.config.warrant_no_add_days_before_last_trade:
                        reasons.append("Adding warrants/CBBCs is blocked near last trading day.")

        return RiskResult(allowed=not reasons, reasons=tuple(reasons))


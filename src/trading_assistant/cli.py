from __future__ import annotations

import argparse
import json

from .audit import AuditLog
from .config import load_config
from .domain import Cash, Instrument, Market, PortfolioSnapshot, SecurityType, Side
from .drafts import create_limit_draft
from .portfolio_state import get_monitoring_payload, get_portfolio_payload
from .risk import RiskEngine
from .brokers.simulated import SimulatedBroker


def health() -> int:
    config = load_config()
    print(
        json.dumps(
            {
                "status": "ok",
                "broker": config.broker.default,
                "single_order_max_usd": config.risk.single_order_max_usd,
            },
            indent=2,
        )
    )
    return 0


def demo_draft() -> int:
    config = load_config()
    broker = SimulatedBroker(cash_usd=3000)
    soxx = Instrument(
        symbol="AAPL",
        market=Market.US,
        security_type=SecurityType.ETF,
        theme="ai_semiconductor_storage",
        name="iShares Semiconductor ETF",
    )
    broker.set_quote(soxx, bid=580.0, ask=580.8, last=580.4)
    draft = create_limit_draft(
        soxx,
        side=Side.BUY,
        quantity=1,
        limit_price=575.0,
        reason="Demo only: semiconductor starter position pullback draft.",
        failure_plan="If price rebounds above the validity band, regenerate the draft.",
    )
    portfolio = PortfolioSnapshot(cash=Cash(available_usd=3000), holdings=())
    risk = RiskEngine(config.risk).check(draft, broker.get_quote(soxx), portfolio)
    AuditLog("data/runtime/audit.sqlite3").append(
        "demo_draft_created",
        {"draft": draft, "risk": risk},
        order_intent_id=draft.order_intent_id,
    )
    print(
        json.dumps(
            {
                "draft": {
                    "order_intent_id": draft.order_intent_id,
                    "symbol": draft.instrument.symbol,
                    "side": draft.side.value,
                    "quantity": draft.quantity,
                    "limit_price": draft.limit_price,
                    "notional": draft.notional,
                    "reason": draft.reason,
                    "validity_seconds": draft.validity_seconds,
                },
                "risk": {
                    "allowed": risk.allowed,
                    "reasons": list(risk.reasons),
                },
            },
            indent=2,
        )
    )
    return 0


def portfolio() -> int:
    print(json.dumps(get_portfolio_payload(), indent=2, ensure_ascii=False))
    return 0


def monitoring() -> int:
    print(json.dumps(get_monitoring_payload(), indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")
    subparsers.add_parser("portfolio")
    subparsers.add_parser("monitoring")
    subparsers.add_parser("demo-draft")
    args = parser.parse_args(argv)

    if args.command == "health":
        return health()
    if args.command == "portfolio":
        return portfolio()
    if args.command == "monitoring":
        return monitoring()
    if args.command == "demo-draft":
        return demo_draft()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


from __future__ import annotations

from copy import deepcopy
from typing import Any

from .market_data import get_live_quotes


# Public builds start with an explicitly synthetic portfolio. Real account snapshots
# are imported at runtime and belong only in the ignored application data directory.
CURRENT_PORTFOLIO: dict[str, Any] = {
    "as_of": "2025-01-02T16:00:00+00:00",
    "source": "bundled_synthetic_demo",
    "price_status": "demo_data_requires_account_import",
    "pending_orders": [],
    "account": {
        "net_assets_usd": 10000.0,
        "securities_market_value_usd": 3600.0,
        "cash_buying_power_usd": 6400.0,
        "risk_status": "demo",
    },
    "holdings": [
        {
            "symbol": "AAPL",
            "name": "Apple (synthetic example)",
            "market": "US",
            "security_type": "stock",
            "quantity": 5,
            "currency": "USD",
            "market_value": 1000.0,
            "screenshot_price": 200.0,
            "average_cost": 180.0,
            "theme": "large_cap_technology",
            "monitor_priority": "normal",
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft (synthetic example)",
            "market": "US",
            "security_type": "stock",
            "quantity": 4,
            "currency": "USD",
            "market_value": 1600.0,
            "screenshot_price": 400.0,
            "average_cost": 360.0,
            "theme": "large_cap_technology",
            "monitor_priority": "normal",
        },
        {
            "symbol": "SPY",
            "name": "S&P 500 ETF (synthetic example)",
            "market": "US",
            "security_type": "etf",
            "quantity": 2,
            "currency": "USD",
            "market_value": 1000.0,
            "screenshot_price": 500.0,
            "average_cost": 480.0,
            "theme": "broad_market_index",
            "monitor_priority": "normal",
        },
    ],
    "unconfirmed_legacy_holdings": [],
}


def get_portfolio_payload(
    *,
    include_live_quotes: bool = False,
    quote_provider: Any | None = None,
) -> dict[str, Any]:
    payload = deepcopy(CURRENT_PORTFOLIO)
    if include_live_quotes:
        _attach_live_quotes(payload, quote_provider=quote_provider)
    payload["holding_count"] = len(payload["holdings"])
    payload["pending_order_count"] = len(payload["pending_orders"])
    return payload


def get_monitoring_payload(
    *,
    include_live_quotes: bool = False,
    quote_provider: Any | None = None,
) -> dict[str, Any]:
    portfolio = get_portfolio_payload(include_live_quotes=include_live_quotes, quote_provider=quote_provider)
    rules = _build_monitoring_rules(portfolio)
    return {
        "as_of": portfolio["as_of"],
        "source": portfolio["source"],
        "price_status": portfolio["price_status"],
        "live_quote_summary": portfolio.get("live_quote_summary"),
        "account": portfolio["account"],
        "holding_count": portfolio["holding_count"],
        "pending_order_count": portfolio["pending_order_count"],
        "rules": rules,
        "action_guidance": [],
        "urgent_count": 0,
    }


def _attach_live_quotes(payload: dict[str, Any], *, quote_provider: Any | None = None) -> None:
    provider = quote_provider or get_live_quotes
    symbols = [holding["symbol"] for holding in payload["holdings"]]
    quote_map = provider(symbols)
    live_count = 0

    for holding in payload["holdings"]:
        quote = quote_map.get(holding["symbol"]) or {
            "symbol": holding["symbol"],
            "status": "unavailable",
            "message": "行情源未返回该标的。",
        }
        holding["live_quote"] = quote
        if quote.get("status") == "live" and isinstance(quote.get("price"), (int, float)):
            live_count += 1
            holding["live_price"] = quote["price"]
            holding["live_market_value"] = round(float(quote["price"]) * float(holding["quantity"]), 4)
            holding["display_price_source"] = "live_quote"
        else:
            holding["live_price"] = None
            holding["live_market_value"] = None
            holding["display_price_source"] = "snapshot_fallback"

    total = len(payload["holdings"])
    payload["live_quote_summary"] = {
        "provider": "configured_market_data",
        "total": total,
        "live": live_count,
        "fallback": total - live_count,
        "status": "ok" if live_count == total else "partial" if live_count else "unavailable",
    }
    payload["price_status"] = (
        "live_quotes_ok"
        if live_count == total
        else "live_quotes_partial_snapshot_fallback"
        if live_count
        else "live_quotes_unavailable_snapshot_fallback"
    )


def _build_monitoring_rules(_portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "legacy-endpoint-deprecated",
            "symbol": None,
            "severity": "info",
            "status": "deprecated",
            "title": "旧监控接口已停用个股硬编码规则",
            "detail": "请使用 /api/v1/decisions/refresh 和设置页中的透明风险规则。",
        }
    ]

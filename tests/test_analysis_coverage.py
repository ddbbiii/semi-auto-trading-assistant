from __future__ import annotations

from datetime import datetime, timezone

from trading_assistant import llm
from trading_assistant.api import _derive_holding_pnl, _model_analysis_context
from trading_assistant.decision_engine import build_decisions
from trading_assistant.providers import _select_futu_market_price


def _portfolio() -> tuple[dict, dict]:
    now = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    snapshot = {
        "as_of": now.isoformat(),
        "source": "confirmed_test",
        "account": {"name": "测试账户"},
        "holdings": [
            {
                "symbol": "AAA",
                "name": "甲公司",
                "market": "US",
                "security_type": "stock",
                "quantity": 2,
                "currency": "USD",
                "market_value": 200,
                "live_market_value": 220,
                "average_cost": 100,
                "theme": "主题甲",
                "available_quantity": 2,
                "live_quote": {
                    "status": "live",
                    "provider": "test",
                    "price": 110,
                    "previous_close": 100,
                    "change_percent": 10,
                    "change_source": "derived_from_previous_close",
                    "observed_at": now.isoformat(),
                    "market_session": "regular",
                    "price_session": "regular",
                },
            },
            {
                "symbol": "BBB",
                "name": "乙公司",
                "market": "CN",
                "security_type": "stock",
                "quantity": 1,
                "currency": "CNY",
                "market_value": 80,
                "live_market_value": 80,
                "average_cost": 100,
                "theme": "主题乙",
                "available_quantity": None,
                "live_quote": {
                    "status": "live",
                    "provider": "test",
                    "price": 80,
                    "previous_close": 82,
                    "change_percent": -2.439,
                    "change_source": "provider",
                    "observed_at": now.isoformat(),
                    "market_session": "regular",
                    "price_session": "regular",
                },
            },
        ],
    }
    summary = {
        "estimated_total_cny": 1620,
        "theme_concentration": [
            {"theme": "主题甲", "value_cny": 1540, "weight_percent": 95.06},
            {"theme": "主题乙", "value_cny": 80, "weight_percent": 4.94},
        ],
        "fx": {"rates_to_cny": {"USD": 7, "HKD": 0.9, "CNY": 1}, "provider": "test", "actionable": True},
    }
    return snapshot, summary


def test_model_context_uses_derived_metrics_without_raw_position_values() -> None:
    snapshot, summary = _portfolio()
    context = _model_analysis_context(
        snapshot,
        [{"symbol": "AAA", "status": "active", "thesis_summary": "需求持续增长", "information_grade": "B"}],
        summary,
    )

    first = context["holdings"][0]
    coverage = {item["key"]: item for item in context["data_coverage"]}

    assert "quantity" not in first
    assert "average_cost" not in first
    assert "market_value" not in first
    assert first["invested_weight_percent"] == 95.06
    assert first["estimated_return_percent"] == 10.0
    assert first["return_source"] == "derived_from_cost"
    assert first["user_rule"]["thesis_summary"] == "需求持续增长"
    assert coverage["quantity"]["status"] == "available"
    assert coverage["cost_basis"]["status"] == "available"
    assert coverage["estimated_return"]["status"] == "derived"
    assert coverage["user_profile"]["status"] == "partial"
    assert coverage["account_weight"]["status"] == "missing"


def test_model_cannot_replace_authoritative_data_limitations() -> None:
    snapshot, summary = _portfolio()
    context = _model_analysis_context(snapshot, [], summary)
    report = llm._normalize_analysis_report(
        {
            "headline": "测试",
            "conclusion": "测试结论",
            "market_facts": [{"label": "行情", "detail": "完整", "tone": "positive"}],
            "reasoning": [{"title": "规则", "detail": "未触发", "tone": "neutral"}],
            "limitations": ["缺少持仓数量、成本和市值。"],
        },
        [],
        context,
        "测试结论",
    )

    assert all("缺少持仓数量" not in item for item in report["limitations"])
    assert any("账户净资产和现金" in item for item in report["limitations"])
    assert any("投资逻辑仅覆盖 0/2" in item for item in report["limitations"])
    assert report["data_coverage"] == context["data_coverage"]


def test_futu_change_percent_is_derived_when_provider_field_is_missing() -> None:
    quote = _select_futu_market_price(
        {
            "last_price": 110,
            "prev_close_price": 100,
            "change_rate": None,
            "pre_price": None,
            "after_price": None,
            "overnight_price": None,
        },
        "AAA",
        now=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
    )

    assert quote["change_percent"] == 10.0
    assert quote["change_source"] == "derived_from_previous_close"


def test_hard_exit_requires_confirmed_available_quantity() -> None:
    now = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
    holding = {
        "symbol": "12345.HK",
        "name": "测试权证",
        "market": "HK",
        "security_type": "warrant",
        "quantity": 5000,
        "available_quantity": None,
        "currency": "HKD",
        "market_value": 2500,
        "average_cost": 1,
    }
    snapshot = {"as_of": now.isoformat(), "source": "test", "account": {}, "holdings": [holding]}
    quotes = {
        "12345.HK": {
            "status": "live",
            "provider": "test",
            "price": 0.5,
            "bid": 0.49,
            "ask": 0.5,
            "market_session": "regular",
            "price_session": "regular",
            "observed_at": now.isoformat(),
        }
    }
    profiles = [{"symbol": "12345.HK", "status": "active", "stop_price": 0.8, "position_intent": "derivative"}]

    blocked = build_decisions(snapshot, quotes, risk_settings={"max_single_position_percent": 100}, risk_profiles=profiles, now=now)[0]
    assert blocked.action == "exit"
    assert blocked.quantity_delta is None
    assert blocked.order_draft is None
    assert "可卖数量尚未同步" in blocked.current_limit

    holding["available_quantity"] = 3000
    ready = build_decisions(snapshot, quotes, risk_settings={"max_single_position_percent": 100}, risk_profiles=profiles, now=now)[0]
    assert ready.quantity_delta == -3000
    assert ready.order_draft is not None
    assert ready.order_draft.quantity == 3000


def test_pnl_is_derived_from_confirmed_cost_without_replacing_broker_values() -> None:
    holding = {"quantity": 2, "average_cost": 100, "holding_pnl": None, "holding_pnl_percent": None}
    _derive_holding_pnl(holding, 110)

    assert holding["holding_pnl"] == 20
    assert holding["holding_pnl_percent"] == 10
    assert holding["holding_pnl_source"] == "derived_from_cost"

    reported = {"quantity": 2, "average_cost": 100, "holding_pnl": 18, "holding_pnl_percent": 9}
    _derive_holding_pnl(reported, 110)
    assert reported["holding_pnl"] == 18
    assert reported["holding_pnl_percent"] == 9
    assert reported["holding_pnl_source"] == "broker_reported"


def test_target_weight_is_not_evaluated_without_account_net_assets() -> None:
    now = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    snapshot = {
        "as_of": now.isoformat(),
        "source": "test",
        "account": {},
        "holdings": [{
            "symbol": "AAA", "name": "甲公司", "market": "US", "security_type": "stock",
            "quantity": 1, "available_quantity": 1, "currency": "USD", "market_value": 100,
            "average_cost": 90, "theme": "主题甲",
        }],
    }
    quotes = {"AAA": {
        "status": "live", "provider": "test", "price": 100, "bid": 99, "ask": 101,
        "market_session": "regular", "price_session": "regular", "observed_at": now.isoformat(),
    }}
    profiles = [{
        "symbol": "AAA", "status": "active", "target_weight_percent": 20,
        "buy_add_conditions": "基本面确认后分批买入",
    }]

    decisions = build_decisions(
        snapshot,
        quotes,
        risk_settings={"max_single_position_percent": 100},
        risk_profiles=profiles,
        now=now,
    )

    assert decisions == []

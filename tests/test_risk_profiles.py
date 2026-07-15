from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from trading_assistant.api import create_app
from trading_assistant.db import Store


def snapshot(quantity: float, *, as_of: datetime | None = None) -> dict:
    return {
        "as_of": (as_of or datetime.now(timezone.utc)).isoformat(),
        "source": "test_confirmed",
        "account": {},
        "holdings": [
            {
                "symbol": "TEST",
                "name": "测试标的",
                "market": "US",
                "security_type": "stock",
                "quantity": quantity,
                "currency": "USD",
                "market_value": 1000 if quantity else 0,
                "price": 100,
                "average_cost": 90,
            }
        ],
    }


def test_risk_settings_and_user_profile_round_trip() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'risk.sqlite3').as_posix()}")
        store.create_schema()
        store.save_snapshot(snapshot(10))
        current = store.latest_snapshot()
        assert current is not None
        store.update_risk_settings(
            {
                "max_single_position_percent": 30,
                "daily_move_alert_percent": 10,
                "warrant_expiry_warning_days": 21,
                "target_weight_tolerance_percent": 3,
            }
        )
        store.replace_user_risk_profiles(
            [
                {
                    "symbol": "TEST",
                    "stop_price": 80,
                    "target_weight_percent": 20,
                    "thesis_invalidation": "收入增速失效",
                    "thesis_summary": "测试投资论文",
                    "information_grade": "A",
                    "research_confidence": "high",
                    "investment_certainty": "medium",
                    "strongest_bear_case": "行业需求下滑",
                    "buy_add_conditions": "估值回到合理区间",
                    "reduce_conditions": "风险收益恶化",
                    "exit_invalidation_conditions": "核心业务失效",
                    "bear_scenario": "需求下降",
                    "base_scenario": "稳健增长",
                    "bull_scenario": "份额提升",
                    "position_intent": "long_term",
                    "price_response": "stop_adding",
                    "expiry_date": None,
                }
            ],
            current,
        )
        settings = store.risk_settings()
        profiles = store.risk_profiles(active_only=True)
        store.close()

    assert settings["max_single_position_percent"] == 30
    assert profiles[0]["symbol"] == "TEST"
    assert profiles[0]["stop_price"] == 80
    assert profiles[0]["thesis_summary"] == "测试投资论文"
    assert profiles[0]["information_grade"] == "A"
    assert profiles[0]["research_confidence"] == "high"
    assert profiles[0]["investment_certainty"] == "medium"
    assert profiles[0]["price_response"] == "stop_adding"
    assert profiles[0]["status"] == "active"


def test_cleared_profile_does_not_reactivate_when_symbol_returns() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'risk.sqlite3').as_posix()}")
        store.create_schema()
        store.save_snapshot(snapshot(10))
        current = store.latest_snapshot()
        assert current is not None
        store.replace_user_risk_profiles(
            [{"symbol": "TEST", "stop_price": 80, "target_weight_percent": None, "thesis_invalidation": "", "expiry_date": None}],
            current,
        )

        store.save_snapshot(snapshot(0))
        cleared = store.latest_snapshot()
        assert cleared is not None
        store.reconcile_risk_profiles(cleared)
        assert store.risk_profiles()[0]["status"] == "inactive_cleared"

        store.save_snapshot(snapshot(5))
        returned = store.latest_snapshot()
        assert returned is not None
        store.reconcile_risk_profiles(returned)
        profile = store.risk_profiles()[0]
        store.close()

    assert profile["status"] == "inactive_cleared"


def test_risk_settings_api_returns_transparent_refresh_summary() -> None:
    def quotes(symbols: list[str], **_kwargs: object) -> dict[str, dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            symbol: {
                "symbol": symbol,
                "status": "live",
                "provider": "test",
                "price": 100.0,
                "bid": 99.9,
                "ask": 100.1,
                "observed_at": now,
            }
            for symbol in symbols
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'risk.sqlite3').as_posix()}")
        store.create_schema()
        store.save_snapshot(snapshot(10))
        app = create_app(store, schedule=False)
        with patch("trading_assistant.api.get_quotes", side_effect=quotes):
            with TestClient(app) as client:
                saved = client.put(
                    "/api/v1/settings/risk",
                    json={
                        "max_single_position_percent": 100,
                        "daily_move_alert_percent": 20,
                        "warrant_expiry_warning_days": 30,
                        "target_weight_tolerance_percent": 2,
                        "profiles": [{"symbol": "TEST", "target_weight_percent": 100, "thesis_invalidation": ""}],
                    },
                )
                refreshed = client.post("/api/v1/decisions/refresh")

    assert saved.status_code == 200
    assert saved.json()["active_profile_count"] == 1
    assert refreshed.status_code == 200
    assert refreshed.json()["summary"]["checked_holdings"] == 1
    assert refreshed.json()["summary"]["active_user_rules"] == 1
    assert refreshed.json()["summary"]["model_status"] == "skipped_no_decisions"


def test_investment_policy_api_exposes_canonical_chinese_rules() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'risk.sqlite3').as_posix()}")
        store.create_schema()
        app = create_app(store, schedule=False)
        with TestClient(app) as client:
            response = client.get("/api/v1/settings/investment-policy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["research"]["information_grades"]["A"].startswith("公司公告")
    assert set(payload["review"]["responses"]) == {"review", "stop_adding", "reduce", "exit"}
    assert "长期股票" in payload["instrument_rules"]["long_term"]

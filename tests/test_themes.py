from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch

from trading_assistant.api import _portfolio_summary
from trading_assistant.db import Store
from trading_assistant.llm import classify_security_themes
from trading_assistant.themes import ensure_security_themes, resolve_security_themes


def test_builtin_themes_are_persisted_independently_from_snapshot() -> None:
    holdings = [
        {"symbol": "SPY", "name": "S&P 500 ETF", "market": "US", "security_type": "etf", "theme": ""},
        {"symbol": "AAPL", "name": "Apple", "market": "US", "security_type": "stock", "theme": ""},
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'themes.sqlite3').as_posix()}")
        store.create_schema()

        themes = ensure_security_themes(store, holdings)
        persisted = store.security_themes()
        store.close()

    assert themes == {"SPY": "宽基指数", "AAPL": "消费电子"}
    assert persisted["SPY"]["source"] == "built_in"
    assert persisted["AAPL"]["theme"] == "消费电子"


def test_unknown_security_uses_model_and_persists_result() -> None:
    holdings = [{"symbol": "NEW", "name": "新标的", "market": "US", "security_type": "stock", "theme": ""}]
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'themes.sqlite3').as_posix()}")
        store.create_schema()
        with patch(
            "trading_assistant.themes.classify_security_themes",
            return_value={"NEW": "企业软件与数字化"},
        ):
            themes = ensure_security_themes(store, holdings)
        persisted = store.security_themes()
        store.close()

    assert themes["NEW"] == "企业软件与数字化"
    assert persisted["NEW"]["source"] == "model_api"


def test_model_theme_request_excludes_portfolio_and_account_data() -> None:
    security = {
        "symbol": "NEW",
        "name": "新标的",
        "market": "US",
        "security_type": "stock",
        "quantity": 999999,
        "market_value": 888888,
        "account_secret": "do-not-send",
    }
    with patch("trading_assistant.llm.status", return_value={"status": "configured"}), patch(
        "trading_assistant.llm._request_json",
        return_value={"items": [{"symbol": "NEW", "theme": "企业软件与数字化"}]},
    ) as request_json:
        result = classify_security_themes([security], ("企业软件与数字化", "其他"))

    prompt = request_json.call_args.args[0]
    assert result == {"NEW": "企业软件与数字化"}
    assert "999999" not in prompt
    assert "888888" not in prompt
    assert "do-not-send" not in prompt


def test_theme_concentration_excludes_closed_positions() -> None:
    snapshot = {
        "holdings": [
            {
                "symbol": "AAPL",
                "quantity": 5,
                "market_value": 100,
                "live_market_value": None,
                "currency": "USD",
                "theme": "消费电子",
            },
            {
                "symbol": "MSFT",
                "quantity": 1,
                "market_value": 100,
                "live_market_value": None,
                "currency": "CNY",
                "theme": "AI 平台与云服务",
            },
            {
                "symbol": "00001.HK",
                "quantity": 0,
                "market_value": 1000,
                "live_market_value": None,
                "currency": "HKD",
                "theme": "衍生品",
            },
        ]
    }
    fx = {
        "rates_to_cny": {"USD": 7.0, "HKD": 0.9, "CNY": 1.0},
        "provider": "test",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'themes.sqlite3').as_posix()}")
        store.create_schema()
        with patch("trading_assistant.api.get_rates_to_cny", return_value=fx):
            summary = _portfolio_summary(snapshot, store)
        store.close()

    assert summary["estimated_total_cny"] == 800.0
    assert summary["theme_concentration"] == [
        {"theme": "消费电子", "value_cny": 700.0, "weight_percent": 87.5},
        {"theme": "AI 平台与云服务", "value_cny": 100.0, "weight_percent": 12.5},
    ]


def test_legacy_snapshot_theme_is_normalized_without_model_call() -> None:
    themes = resolve_security_themes(
        [{"symbol": "SPY", "theme": "broad_market_index"}],
        stored={},
    )

    assert themes["SPY"] == "宽基指数"

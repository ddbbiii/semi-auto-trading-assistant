from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from trading_assistant.analysis_schedule import enabled_sessions_at, market_session_for_symbol, market_sessions_at, schedule_status
from trading_assistant.api import create_app
from trading_assistant.db import Store


DEFAULTS = {
    "interval_minutes": 120,
    "analyze_us_premarket": False,
    "analyze_regular_session": True,
    "analyze_us_afterhours": False,
}


def test_default_analysis_settings_are_persisted() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'schedule.sqlite3').as_posix()}")
        store.create_schema()
        settings = store.analysis_settings()
        store.close()

    assert settings["interval_minutes"] == 120
    assert settings["analyze_us_premarket"] is False
    assert settings["analyze_regular_session"] is True
    assert settings["analyze_us_afterhours"] is False


def test_analysis_settings_update_round_trips() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'schedule.sqlite3').as_posix()}")
        store.create_schema()
        settings = store.update_analysis_settings(
            {
                "interval_minutes": 90,
                "analyze_us_premarket": True,
                "analyze_regular_session": False,
                "analyze_us_afterhours": True,
            }
        )
        store.close()

    assert settings["interval_minutes"] == 90
    assert settings["analyze_us_premarket"] is True
    assert settings["analyze_regular_session"] is False
    assert settings["analyze_us_afterhours"] is True


def test_market_sessions_cover_china_and_us_extended_hours() -> None:
    assert market_sessions_at(datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)) == ["cn_regular", "hk_regular"]
    assert market_sessions_at(datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)) == ["us_premarket"]
    assert market_sessions_at(datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)) == ["us_regular"]
    assert market_sessions_at(datetime(2026, 7, 13, 21, 0, tzinfo=timezone.utc)) == ["us_afterhours"]


def test_market_session_for_us_symbol_distinguishes_extended_hours() -> None:
    assert market_session_for_symbol("AAPL", datetime(2026, 7, 13, 13, 8, tzinfo=timezone.utc)) == "premarket"
    assert market_session_for_symbol("AAPL", datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)) == "regular"
    assert market_session_for_symbol("AAPL", datetime(2026, 7, 13, 21, 0, tzinfo=timezone.utc)) == "afterhours"


def test_session_toggles_apply_to_expected_markets() -> None:
    us_pre = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    us_after = datetime(2026, 7, 13, 21, 0, tzinfo=timezone.utc)
    cn_regular = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)

    assert enabled_sessions_at(DEFAULTS, us_pre) == []
    assert enabled_sessions_at(DEFAULTS, us_after) == []
    assert enabled_sessions_at(DEFAULTS, cn_regular) == ["cn_regular", "hk_regular"]

    extended = DEFAULTS | {"analyze_us_premarket": True, "analyze_us_afterhours": True}
    assert enabled_sessions_at(extended, us_pre) == ["us_premarket"]
    assert enabled_sessions_at(extended, us_after) == ["us_afterhours"]


def test_schedule_is_due_only_after_interval_inside_enabled_session() -> None:
    now = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    not_due = schedule_status(DEFAULTS, last_analysis_at=now - timedelta(minutes=90), now=now)
    due = schedule_status(DEFAULTS, last_analysis_at=now - timedelta(minutes=121), now=now)
    outside = schedule_status(
        DEFAULTS,
        last_analysis_at=now - timedelta(minutes=121),
        now=datetime(2026, 7, 13, 21, 0, tzinfo=timezone.utc),
    )

    assert not_due["due"] is False
    assert due["due"] is True
    assert due["enabled_current_sessions"] == ["美股盘中"]
    assert outside["due"] is False


def test_analysis_settings_api_validates_and_persists_updates() -> None:
    def unavailable_quotes(symbols: list[str], **_kwargs: object) -> dict[str, dict[str, object]]:
        return {
            symbol: {
                "symbol": symbol,
                "provider": "test",
                "status": "unavailable",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for symbol in symbols
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'schedule.sqlite3').as_posix()}")
        app = create_app(store, schedule=False)
        with patch("trading_assistant.api.get_quotes", side_effect=unavailable_quotes):
            with TestClient(app) as client:
                response = client.put(
                    "/api/v1/settings/analysis",
                    json={
                        "interval_minutes": 180,
                        "analyze_us_premarket": True,
                        "analyze_regular_session": True,
                        "analyze_us_afterhours": True,
                    },
                )
                invalid = client.put(
                    "/api/v1/settings/analysis",
                    json={
                        "interval_minutes": 10,
                        "analyze_us_premarket": False,
                        "analyze_regular_session": True,
                        "analyze_us_afterhours": False,
                    },
                )
                persisted = client.get("/api/v1/settings/analysis")

    assert response.status_code == 200
    assert response.json()["interval_minutes"] == 180
    assert response.json()["analyze_us_afterhours"] is True
    assert invalid.status_code == 422
    assert persisted.json()["interval_minutes"] == 180

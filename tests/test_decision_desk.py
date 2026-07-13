from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from trading_assistant.api import create_app
from trading_assistant.db import Store
from trading_assistant.decision_engine import build_decisions, quote_quality
from trading_assistant.imports import (
    _parse_ocr_number,
    _reconcile_position_values,
    _normalize_symbol,
    _declared_holding_count,
    _rows_from_broker_layout,
    preview_import,
    preview_import_batch,
)
from trading_assistant.llm import _extract_responses_text, _humanize_internal_codes
from trading_assistant.portfolio_state import CURRENT_PORTFOLIO
from trading_assistant.providers import _futu_observed_at, _select_futu_market_price


def unavailable_quotes(symbols: list[str], **_kwargs) -> dict[str, dict[str, object]]:
    return {
        symbol: {
            "symbol": symbol,
            "provider": "test",
            "status": "unavailable",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "message": "test unavailable",
        }
        for symbol in symbols
    }


def test_stale_snapshot_blocks_precise_action() -> None:
    now = datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc)
    decisions = build_decisions(CURRENT_PORTFOLIO, unavailable_quotes([]), now=now)

    sync = next(item for item in decisions if item.symbol == "PORTFOLIO")
    assert sync.action == "verify"
    assert sync.data_quality.actionable is False
    assert sync.quantity_delta is None


def test_user_confirmed_stop_builds_non_executable_exit_draft() -> None:
    now = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
    snapshot = {
        "as_of": (now - timedelta(minutes=5)).isoformat(),
        "source": "synthetic_test",
        "account": {},
        "holdings": [
            {
                "symbol": "00001.HK",
                "name": "测试权证",
                "market": "HK",
                "security_type": "warrant",
                "quantity": 1000,
                "currency": "HKD",
                "market_value": 700,
            }
        ],
    }
    quotes = {
        "00001.HK": {
            "status": "live",
            "provider": "test",
            "price": 0.70,
            "bid": 0.70,
            "ask": 0.71,
            "observed_at": (now - timedelta(seconds=20)).isoformat(),
        }
    }

    decisions = build_decisions(
        snapshot,
        quotes,
        risk_profiles=[
            {
                "symbol": "00001.HK",
                "stop_price": 0.75,
                "target_weight_percent": None,
                "thesis_invalidation": "正股方向与对冲逻辑不再成立",
                "status": "active",
            }
        ],
        now=now,
    )
    item = next(decision for decision in decisions if decision.symbol == "00001.HK")

    assert item.action == "exit"
    assert item.name == "测试权证"
    assert item.data_quality.actionable is True
    assert item.data_quality.execution_ready is True
    assert item.order_draft is not None
    assert item.order_draft.executable is False


def test_csv_preview_maps_chinese_headers() -> None:
    data = "证券代码,证券名称,数量,持仓市值,现价,成本价\nAAPL,Apple,5,1000,200,180\n".encode("utf-8")
    preview = preview_import("holdings.csv", "text/csv", data)

    assert len(preview.holdings) == 1
    assert preview.holdings[0].symbol == "AAPL"
    assert preview.holdings[0].market == "US"
    assert preview.holdings[0].currency == "USD"


def test_multiple_screenshots_merge_into_one_confirmation_preview() -> None:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
    image_data = buffer.getvalue()

    empty_ocr_data = {key: [] for key in ("text", "left", "top", "width", "height", "conf")}
    with patch("trading_assistant.imports.pytesseract.image_to_data", return_value=empty_ocr_data), patch(
        "trading_assistant.imports.pytesseract.image_to_string",
        side_effect=["AAPL Apple 5 1000 200 180", "MSFT Microsoft 4 1600 400 360"],
    ):
        preview = preview_import_batch(
            [
                ("美股.png", "image/png", image_data),
                ("A股.png", "image/png", image_data),
            ]
        )

    assert preview.parser == "multi_image_ocr"
    assert preview.file_name == "2 张账户截图"
    assert [holding.symbol for holding in preview.holdings] == ["AAPL", "MSFT"]


def test_multiple_files_reject_spreadsheet_mixing() -> None:
    with pytest.raises(ValueError, match="多文件导入只支持截图"):
        preview_import_batch([("持仓.csv", "text/csv", b""), ("截图.png", "image/png", b"")])


def test_broker_layout_pairs_two_line_columns() -> None:
    data = {
        "text": ["美股", "代码", "AAPL", "1,000.00", "200.000", "5", "180.000"],
        "left": [57, 149, 56, 486, 769, 673, 837],
        "top": [100, 300, 500, 410, 410, 500, 500],
        "width": [90, 65, 103, 205, 212, 18, 145],
        "height": [40, 37, 31, 47, 42, 31, 32],
        "conf": [95, 95, 95, 95, 95, 95, 95],
    }
    with patch(
        "trading_assistant.imports._ocr_crop",
        side_effect=["Apple", "AAPL", "5", "1,000.00", "200.000", "180.000"],
    ):
        rows, warnings = _rows_from_broker_layout(Image.new("RGB", (1216, 2640), "white"), data)

    assert warnings == []
    assert rows == [
        {
            "symbol": "AAPL",
            "name": "Apple",
            "market": "US",
            "currency": "USD",
            "quantity": 5.0,
            "market_value": 1000.0,
            "price": 200.0,
            "average_cost": 180.0,
        }
    ]


def test_ocr_number_and_position_consistency_repairs_common_errors() -> None:
    assert _parse_ocr_number("227165", decimals=3) == 227.165
    assert _normalize_symbol("00001 7", "HK") == "00001.HK"
    market_value, price, warning = _reconcile_position_values(
        "AAPL", 5, [1000.0, 1000.0], [220.0, 200.0]
    )
    assert (market_value, price, warning) == (1000.0, 200.0, None)

    market_value, price, warning = _reconcile_position_values(
        "00001.HK", 1000, [1500.0, 1500.0], [1.0, 1.0]
    )
    assert (market_value, price) == (1000.0, 1.0)
    assert warning and "数量×现价" in warning


def test_declared_holding_count_is_extracted_for_completeness_check() -> None:
    tokens = [
        {"text": "持仓", "left": 50, "top": 100, "width": 80, "height": 40, "confidence": 95},
        {"text": "(11)", "left": 145, "top": 102, "width": 60, "height": 40, "confidence": 95},
    ]
    assert _declared_holding_count(tokens) == 11


def test_import_preview_api_accepts_multiple_screenshots() -> None:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
    image_data = buffer.getvalue()

    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'test.sqlite3').as_posix()}")
        app = create_app(store, schedule=False)
        empty_ocr_data = {key: [] for key in ("text", "left", "top", "width", "height", "conf")}
        with patch("trading_assistant.imports.pytesseract.image_to_data", return_value=empty_ocr_data), patch(
            "trading_assistant.imports.pytesseract.image_to_string",
            side_effect=["AAPL Apple 5 1000 200 180", "MSFT Microsoft 4 1600 400 360"],
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/import/preview",
                    files=[
                        ("files", ("美股.png", image_data, "image/png")),
                        ("files", ("A股.png", image_data, "image/png")),
                    ],
                )

    assert response.status_code == 200
    assert response.json()["parser"] == "multi_image_ocr"
    assert len(response.json()["holdings"]) == 2


def test_futu_market_timestamp_preserves_fractional_seconds_and_timezone() -> None:
    observed = _futu_observed_at("2026-07-10 20:01:08.085", "US.GOOG")

    assert observed == "2026-07-11T00:01:08.085000+00:00"


def test_futu_snapshot_uses_premarket_price_during_us_premarket() -> None:
    quote = _select_futu_market_price(
        {
            "last_price": 200.0,
            "change_rate": 1.2,
            "pre_price": 198.0,
            "pre_change_rate": -2.98,
            "after_price": 201.0,
        },
        "AAPL",
        now=datetime(2026, 7, 13, 13, 8, tzinfo=timezone.utc),
    )

    assert quote["price"] == 198.0
    assert quote["regular_price"] == 200.0
    assert quote["market_session"] == "premarket"
    assert quote["price_session"] == "premarket"
    assert quote["change_percent"] == -2.98


def test_futu_snapshot_uses_regular_and_afterhours_prices_in_their_sessions() -> None:
    row = {"last_price": 200.0, "after_price": 201.0}

    regular = _select_futu_market_price(row, "AAPL", now=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc))
    afterhours = _select_futu_market_price(row, "AAPL", now=datetime(2026, 7, 13, 21, 0, tzinfo=timezone.utc))

    assert regular["price"] == 200.0
    assert regular["price_session"] == "regular"
    assert afterhours["price"] == 201.0
    assert afterhours["price_session"] == "afterhours"


def test_extract_responses_text_from_raw_http_response() -> None:
    body = {
        "output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"status":"ok"}'}]},
        ]
    }

    assert _extract_responses_text(body) == '{"status":"ok"}'


def test_humanize_internal_data_quality_codes() -> None:
    assert _humanize_internal_codes("quote_stale") == "行情超过当前场景允许的监控时限，系统将通过 API 自动重试"


def test_delayed_intraday_quote_is_usable_for_monitoring_not_execution() -> None:
    now = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
    quality = quote_quality(
        {
            "status": "live",
            "provider": "test",
            "price": 0.76,
            "observed_at": (now - timedelta(minutes=10)).isoformat(),
        },
        now=now,
        snapshot_fresh=True,
        symbol="00001.HK",
    )

    assert quality.actionable is True
    assert quality.usage == "monitoring"
    assert quality.execution_ready is False
    assert "quote_delayed" in quality.issues


def test_fresh_premarket_quote_is_monitoring_data_not_execution_data() -> None:
    now = datetime(2026, 7, 13, 13, 8, tzinfo=timezone.utc)
    quality = quote_quality(
        {
            "status": "live",
            "provider": "futu_opend",
            "price": 198.0,
            "regular_price": 200.0,
            "bid": 197.9,
            "ask": 198.1,
            "market_session": "premarket",
            "price_session": "premarket",
            "observed_at": (now - timedelta(seconds=10)).isoformat(),
        },
        now=now,
        snapshot_fresh=True,
        symbol="AAPL",
    )

    assert quality.actionable is True
    assert quality.usage == "monitoring"
    assert quality.market_status == "open"
    assert quality.execution_ready is False
    assert "extended_hours_monitoring" in quality.issues
    assert "market_closed_reference" not in quality.issues


def test_regular_close_cannot_masquerade_as_premarket_quote() -> None:
    now = datetime(2026, 7, 13, 13, 8, tzinfo=timezone.utc)
    quality = quote_quality(
        {
            "status": "live",
            "provider": "futu_opend",
            "price": 200.0,
            "market_session": "premarket",
            "price_session": "regular_reference",
            "observed_at": now.isoformat(),
        },
        now=now,
        snapshot_fresh=True,
        symbol="AAPL",
    )

    assert quality.actionable is False
    assert quality.execution_ready is False
    assert "extended_quote_unavailable" in quality.issues


def test_recent_closed_market_quote_is_reference_without_manual_verification() -> None:
    now = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)
    quality = quote_quality(
        {
            "status": "live",
            "provider": "test",
            "price": 0.76,
            "observed_at": datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc).isoformat(),
        },
        now=now,
        snapshot_fresh=True,
        symbol="00001.HK",
    )

    assert quality.actionable is True
    assert quality.usage == "reference"
    assert quality.execution_ready is False
    assert "market_closed_reference" in quality.issues


def test_zero_quantity_warrant_does_not_create_verification_decision() -> None:
    now = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
    snapshot = {
        "as_of": now.isoformat(),
        "source": "synthetic_test",
        "account": {},
        "holdings": [{"symbol": "00001.HK", "name": "测试权证", "market": "HK", "security_type": "warrant", "quantity": 0, "currency": "HKD", "market_value": 0}],
    }

    assert all(item.symbol != "00001.HK" for item in build_decisions(snapshot, unavailable_quotes(["00001.HK"]), now=now))


def test_generic_concentration_rule_applies_without_symbol_specific_logic() -> None:
    now = datetime.now(timezone.utc)
    snapshot = {
        "as_of": now.isoformat(),
        "source": "synthetic_test",
        "account": {},
        "holdings": [
            {"symbol": "AAPL", "name": "Apple", "market": "US", "security_type": "stock", "quantity": 45, "currency": "USD", "market_value": 9000},
            {"symbol": "MSFT", "name": "Microsoft", "market": "US", "security_type": "stock", "quantity": 2, "currency": "USD", "market_value": 1000},
        ],
    }
    quotes = {
        "AAPL": {
            "status": "live",
            "provider": "test",
            "price": 30.0,
            "observed_at": (now - timedelta(seconds=20)).isoformat(),
        }
    }

    item = next(
        decision
        for decision in build_decisions(
            snapshot,
            quotes,
            risk_settings={"max_single_position_percent": 20},
            now=now,
        )
        if decision.symbol == "AAPL"
    )

    assert item.action == "reduce"
    assert item.name == "Apple"
    assert item.data_quality.actionable is True
    assert item.target_weight_percent == 20


def test_no_symbol_specific_stop_exists_without_user_profile() -> None:
    now = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
    snapshot = {
        "as_of": now.isoformat(),
        "source": "test",
        "account": {},
        "holdings": [
            {
                "symbol": "00001.HK",
                "name": "测试权证",
                "market": "HK",
                "security_type": "warrant",
                "quantity": 5000,
                "currency": "HKD",
                "market_value": 3500,
            }
        ],
    }
    quotes = {
        "00001.HK": {
            "status": "live",
            "provider": "test",
            "price": 0.70,
            "bid": 0.70,
            "ask": 0.71,
            "observed_at": (now - timedelta(seconds=20)).isoformat(),
        }
    }

    assert build_decisions(snapshot, quotes, risk_settings={"max_single_position_percent": 100}, now=now) == []


def test_dashboard_feedback_and_get_requests_have_no_email_side_effect() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{(Path(temp_dir) / 'test.sqlite3').as_posix()}"
        store = Store(database_url)
        app = create_app(store, schedule=False)
        with patch("trading_assistant.api.get_quotes", side_effect=unavailable_quotes), patch(
            "trading_assistant.api.get_rates_to_cny",
            return_value={
                "rates_to_cny": {"CNY": 1.0, "HKD": 0.92, "USD": 7.2},
                "provider": "test",
                "actionable": False,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "issues": ["test"],
            },
        ), patch(
            "trading_assistant.api.maybe_send_decision_alert_email"
        ) as send_email:
            with TestClient(app) as client:
                dashboard = client.get("/api/v1/dashboard")
                assert dashboard.status_code == 200
                payload = dashboard.json()
                assert 1 <= len(payload["decisions"]) <= 3
                decision_id = payload["decisions"][0]["id"]

                feedback = client.post(
                    f"/api/v1/decisions/{decision_id}/feedback",
                    json={"action": "snoozed", "note": "等待账户同步"},
                )
                assert feedback.status_code == 200
                assert feedback.json()["decision"]["status"] == "snoozed"

                assert client.get("/portfolio").status_code == 200
                assert client.get("/monitoring").status_code == 200

        send_email.assert_not_called()

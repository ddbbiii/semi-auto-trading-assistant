from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from trading_assistant.api import create_app
from trading_assistant.db import Store
from trading_assistant.watchlist_sync import parse_active_watchlist


SAMPLE = """
## Current Watchlist

### 2026-07-13 Active Watchlist

Use this list for current opportunities.

- `SPY`: broad market demonstration.
- `AAPL`: large-cap technology demonstration.
- `MSFT`: software platform demonstration.

### 2026-07-13 Theme Watch Priorities

- `NVDA`: research only, not active.
"""


def unavailable_quotes(symbols: list[str], **_kwargs):
    now = datetime.now(timezone.utc).isoformat()
    return {
        symbol: {
            "symbol": symbol,
            "provider": "test",
            "status": "unavailable",
            "fetched_at": now,
        }
        for symbol in symbols
    }


def test_parser_uses_only_latest_active_watchlist_section() -> None:
    items = parse_active_watchlist(SAMPLE)

    assert [item["symbol"] for item in items] == ["SPY", "AAPL", "MSFT"]
    assert items[0]["name"] == "SPDR S&P 500 ETF Trust"
    assert "NVDA" not in {item["symbol"] for item in items}


def test_store_replaces_watchlist_atomically_and_preserves_order() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'test.sqlite3').as_posix()}")
        store.create_schema()
        store.replace_opportunity_watchlist(parse_active_watchlist(SAMPLE), source="test-finance-md")
        items, metadata = store.opportunity_watchlist()
        store.replace_opportunity_watchlist(items[:2], source="test-update")
        replaced, replaced_metadata = store.opportunity_watchlist()
        store.close()

    assert [item["symbol"] for item in items] == ["SPY", "AAPL", "MSFT"]
    assert metadata["source"] == "test-finance-md"
    assert [item["symbol"] for item in replaced] == ["SPY", "AAPL"]
    assert replaced_metadata["source"] == "test-update"


def test_opportunities_api_reads_persistent_watchlist() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'test.sqlite3').as_posix()}")
        app = create_app(store, schedule=False)
        with patch("trading_assistant.api.get_quotes", side_effect=unavailable_quotes):
            with TestClient(app) as client:
                store.replace_opportunity_watchlist(parse_active_watchlist(SAMPLE), source="finance.md-active-watchlist")
                response = client.get("/api/v1/opportunities")

    assert response.status_code == 200
    payload = response.json()
    assert [item["symbol"] for item in payload["items"]] == ["SPY", "AAPL", "MSFT"]
    assert payload["items"][0]["thesis"].startswith("公开版本的宽基示例")
    assert payload["items"][1]["thesis"].startswith("公开版本的大型科技股示例")
    assert payload["watchlist"]["source"] == "finance.md-active-watchlist"

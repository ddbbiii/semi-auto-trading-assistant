from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from threading import Lock
from typing import Any
from urllib.request import urlopen


DEFAULT_RATES_TO_CNY = {"CNY": 1.0, "HKD": 0.92, "USD": 7.2}
_cache: dict[str, Any] | None = None
_lock = Lock()


def get_rates_to_cny(*, force: bool = False) -> dict[str, Any]:
    global _cache
    now = datetime.now(timezone.utc)
    with _lock:
        if not force and _cache and now - _cache["fetched_at"] < timedelta(minutes=30):
            return _serialize(_cache)
        try:
            with urlopen("https://api.frankfurter.app/latest?from=CNY&to=USD,HKD", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rates = payload.get("rates", {})
            usd = float(rates["USD"])
            hkd = float(rates["HKD"])
            if usd <= 0 or hkd <= 0:
                raise ValueError("invalid FX response")
            _cache = {
                "rates_to_cny": {"CNY": 1.0, "USD": 1 / usd, "HKD": 1 / hkd},
                "provider": "frankfurter_ecb",
                "actionable": True,
                "fetched_at": now,
                "observed_at": datetime.fromisoformat(payload["date"]).replace(tzinfo=timezone.utc),
                "issues": [],
            }
        except Exception as exc:
            _cache = {
                "rates_to_cny": DEFAULT_RATES_TO_CNY.copy(),
                "provider": "configured_fallback",
                "actionable": False,
                "fetched_at": now,
                "observed_at": now,
                "issues": [f"fx_unavailable: {exc}"],
            }
        return _serialize(_cache)


def _serialize(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "fetched_at": value["fetched_at"].isoformat(),
        "observed_at": value["observed_at"].isoformat(),
    }

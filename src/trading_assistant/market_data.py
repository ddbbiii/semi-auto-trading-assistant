from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def get_finnhub_api_key() -> str:
    for name in ("TRADING_ASSISTANT_FINNHUB_API_KEY", "FINNHUB_API_KEY", "NEXT_PUBLIC_FINNHUB_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value

    return ""


def normalize_finnhub_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol.endswith(".HK"):
        code = symbol.removesuffix(".HK")
        normalized_code = code.lstrip("0") or code
        return f"{normalized_code}.HK"
    return symbol


def get_live_quotes(symbols: Iterable[str], api_key: str | None = None) -> dict[str, dict[str, Any]]:
    token = api_key if api_key is not None else get_finnhub_api_key()
    unique_symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    return {symbol: fetch_finnhub_quote(symbol, token) for symbol in unique_symbols}


def fetch_finnhub_quote(symbol: str, api_key: str) -> dict[str, Any]:
    provider_symbol = normalize_finnhub_symbol(symbol)
    fetched_at = datetime.now(timezone.utc).isoformat()
    base_payload: dict[str, Any] = {
        "symbol": symbol,
        "provider": "finnhub",
        "provider_symbol": provider_symbol,
        "fetched_at": fetched_at,
    }

    if not api_key:
        return {
            **base_payload,
            "status": "not_configured",
            "message": "Finnhub API key 未配置，无法主动获取行情。",
        }

    params = urlencode({"symbol": provider_symbol, "token": api_key})
    url = f"{FINNHUB_BASE_URL}/quote?{params}"

    try:
        with urlopen(url, timeout=8) as response:
            raw = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {
            **base_payload,
            "status": "error",
            "message": f"Finnhub 行情请求失败：{exc}",
        }

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            **base_payload,
            "status": "error",
            "message": "Finnhub 返回了无法解析的行情数据。",
        }

    price = _number_or_none(data.get("c"))
    if price is None or price <= 0:
        return {
            **base_payload,
            "status": "unavailable",
            "message": "Finnhub 未返回有效价格，可能不支持该标的或当前无报价。",
        }

    return {
        **base_payload,
        "status": "live",
        "observed_at": datetime.fromtimestamp(float(data["t"]), timezone.utc).isoformat()
        if isinstance(data.get("t"), (int, float)) and data["t"] > 0
        else fetched_at,
        "price": price,
        "change": _number_or_none(data.get("d")),
        "change_percent": _number_or_none(data.get("dp")),
        "previous_close": _number_or_none(data.get("pc")),
        "open": _number_or_none(data.get("o")),
        "high": _number_or_none(data.get("h")),
        "low": _number_or_none(data.get("l")),
    }


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and value == value:
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None

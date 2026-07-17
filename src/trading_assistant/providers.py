from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any, Iterable
from zoneinfo import ZoneInfo
from threading import Lock

from .analysis_schedule import market_session_for_symbol
from .market_data import get_live_quotes


_QUOTE_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
_QUOTE_CACHE_LOCK = Lock()


def to_futu_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.endswith(".HK"):
        return f"HK.{value.removesuffix('.HK').zfill(5)}"
    if value.endswith(".SZ"):
        return f"SZ.{value.removesuffix('.SZ').zfill(6)}"
    if value.endswith(".SS") or value.endswith(".SH"):
        return f"SH.{value.rsplit('.', 1)[0].zfill(6)}"
    return f"US.{value}"


def get_quotes(symbols: Iterable[str], *, force: bool = False) -> dict[str, dict[str, Any]]:
    unique = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    now = datetime.now(timezone.utc)
    with _QUOTE_CACHE_LOCK:
        cached = {
            symbol: payload
            for symbol in unique
            if not force
            and (entry := _QUOTE_CACHE.get(symbol))
            and (now - entry[0]).total_seconds() <= 30
            for payload in (entry[1],)
        }
    pending = [symbol for symbol in unique if symbol not in cached]
    futu_quotes = _get_futu_quotes(pending)
    missing = [symbol for symbol in pending if futu_quotes.get(symbol, {}).get("status") != "live"]
    fallback = get_live_quotes(missing) if missing else {}
    merged: dict[str, dict[str, Any]] = {}
    for symbol in pending:
        primary = futu_quotes.get(symbol)
        if primary and primary.get("status") == "live":
            merged[symbol] = primary
            continue
        secondary = fallback.get(symbol)
        if secondary and secondary.get("status") == "live":
            secondary["fallback_from"] = "futu_opend"
            merged[symbol] = secondary
            continue
        issues = []
        if primary and primary.get("message"):
            issues.append(str(primary["message"]))
        if secondary and secondary.get("message"):
            issues.append(str(secondary["message"]))
        merged[symbol] = {
            "symbol": symbol,
            "status": "unavailable",
            "provider": "futu_opend+finnhub",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "message": "；".join(issues) or "没有可用行情。",
        }
    with _QUOTE_CACHE_LOCK:
        for symbol, payload in merged.items():
            _QUOTE_CACHE[symbol] = (now, payload)
    return cached | merged


def futu_status() -> dict[str, Any]:
    enabled = os.getenv("TRADING_ASSISTANT_FUTU_ENABLED", "0") == "1"
    if not enabled:
        return {"status": "disabled", "host": _futu_host(), "port": _futu_port()}
    try:
        import futu as ft  # type: ignore

        context = ft.OpenQuoteContext(host=_futu_host(), port=_futu_port())
        try:
            ret, state = context.get_global_state()
            if ret != ft.RET_OK:
                return {
                    "status": "error",
                    "host": _futu_host(),
                    "port": _futu_port(),
                    "detail": str(state),
                }
            program_status = state.get("program_status_type") if isinstance(state, dict) else None
            status_label = str(program_status)
            ready = program_status == 10 or status_label.lower().endswith("ready")
            return {
                "status": "connected" if ready else "starting",
                "host": _futu_host(),
                "port": _futu_port(),
                "program_status": status_label,
            }
        finally:
            context.close()
    except Exception as exc:
        return {"status": "error", "host": _futu_host(), "port": _futu_port(), "detail": str(exc)}


def _get_futu_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols or os.getenv("TRADING_ASSISTANT_FUTU_ENABLED", "0") != "1":
        return {}
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        import futu as ft  # type: ignore

        context = ft.OpenQuoteContext(host=_futu_host(), port=_futu_port())
        try:
            code_map = {to_futu_symbol(symbol): symbol for symbol in symbols}
            ret, frame = context.get_market_snapshot(list(code_map))
            if ret != ft.RET_OK:
                raise RuntimeError(str(frame))
            results: dict[str, dict[str, Any]] = {}
            for _, row in frame.iterrows():
                source_code = str(row.get("code", ""))
                symbol = code_map.get(source_code)
                if not symbol:
                    continue
                session_quote = _select_futu_market_price(row, symbol, now=datetime.now(timezone.utc))
                price = session_quote["price"]
                results[symbol] = {
                    "symbol": symbol,
                    "provider": "futu_opend",
                    "provider_symbol": source_code,
                    "fetched_at": fetched_at,
                    "observed_at": _futu_observed_at(row.get("update_time"), source_code) or fetched_at,
                    "status": "live" if price is not None else "unavailable",
                    **session_quote,
                    "bid": _positive(row.get("bid_price")),
                    "ask": _positive(row.get("ask_price")),
                    "open": _positive(row.get("open_price")),
                    "high": _positive(row.get("high_price")),
                    "low": _positive(row.get("low_price")),
                    "previous_close": _positive(row.get("prev_close_price")),
                }
            return results
        finally:
            context.close()
    except Exception as exc:
        return {
            symbol: {
                "symbol": symbol,
                "provider": "futu_opend",
                "status": "error",
                "fetched_at": fetched_at,
                "message": f"OpenD 不可用：{exc}",
            }
            for symbol in symbols
        }


def _select_futu_market_price(row: Any, symbol: str, *, now: datetime | None = None) -> dict[str, Any]:
    session = market_session_for_symbol(symbol, now)
    regular_price = _positive(row.get("last_price"))
    previous_close = _positive(row.get("prev_close_price"))
    session_fields = {
        "premarket": ("pre_price", "pre_change_rate"),
        "afterhours": ("after_price", "after_change_rate"),
        "regular": ("last_price", "change_rate"),
    }
    price_field, change_field = session_fields.get(session, ("last_price", "change_rate"))
    session_price = _positive(row.get(price_field))
    price = session_price or regular_price
    price_session = session if session_price is not None else "regular_reference"
    if session == "regular" and regular_price is not None:
        price_session = "regular"

    reported_change = _number(row.get(change_field)) if session_price is not None else _number(row.get("change_rate"))
    change_percent = reported_change
    change_source = "provider" if reported_change is not None else None
    if change_percent is None:
        baseline = regular_price if session == "afterhours" and session_price is not None else previous_close
        change_percent = _change_percent(price, baseline)
        change_source = "derived_from_regular_close" if session == "afterhours" and session_price is not None else "derived_from_previous_close"

    return {
        "price": price,
        "change_percent": change_percent,
        "change_source": change_source,
        "market_session": session,
        "price_session": price_session,
        "regular_price": regular_price,
        "pre_price": _positive(row.get("pre_price")),
        "after_price": _positive(row.get("after_price")),
        "overnight_price": _positive(row.get("overnight_price")),
    }


def _change_percent(price: float | None, baseline: float | None) -> float | None:
    if price is None or baseline is None or baseline <= 0:
        return None
    return round((price / baseline - 1) * 100, 4)


def _futu_host() -> str:
    return os.getenv("TRADING_ASSISTANT_FUTU_HOST", "127.0.0.1")


def _futu_port() -> int:
    return int(os.getenv("TRADING_ASSISTANT_FUTU_PORT", "11111"))


def _positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _futu_observed_at(value: Any, provider_symbol: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        market = provider_symbol.split(".", 1)[0]
        timezone_name = "America/New_York" if market == "US" else "Asia/Hong_Kong"
        parsed = datetime.fromisoformat(value.strip()).replace(tzinfo=ZoneInfo(timezone_name))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat()

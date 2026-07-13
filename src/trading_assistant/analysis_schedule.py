from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


SESSION_LABELS: dict[str, str] = {
    "cn_regular": "A 股盘中",
    "hk_regular": "港股盘中",
    "us_premarket": "美股盘前",
    "us_regular": "美股盘中",
    "us_afterhours": "美股盘后",
}

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")


def market_sessions_at(now: datetime | None = None) -> list[str]:
    current = _aware_utc(now)
    shanghai = current.astimezone(SHANGHAI)
    new_york = current.astimezone(NEW_YORK)
    sessions: list[str] = []

    if shanghai.weekday() < 5:
        local_time = shanghai.time().replace(tzinfo=None)
        if _within(local_time, time(9, 30), time(11, 30)) or _within(local_time, time(13), time(15)):
            sessions.append("cn_regular")
        if _within(local_time, time(9, 30), time(12)) or _within(local_time, time(13), time(16)):
            sessions.append("hk_regular")

    if new_york.weekday() < 5:
        local_time = new_york.time().replace(tzinfo=None)
        if _within(local_time, time(4), time(9, 30)):
            sessions.append("us_premarket")
        elif _within(local_time, time(9, 30), time(16)):
            sessions.append("us_regular")
        elif _within(local_time, time(16), time(20)):
            sessions.append("us_afterhours")
    return sessions


def market_session_for_symbol(symbol: str, now: datetime | None = None) -> str:
    """Return the active quote session for one security."""
    current = _aware_utc(now)
    value = symbol.strip().upper()
    if value.startswith("HK.") or value.endswith(".HK"):
        local = current.astimezone(ZoneInfo("Asia/Hong_Kong"))
        sessions = ((time(9, 30), time(12)), (time(13), time(16)))
    elif value.startswith(("SZ.", "SH.")) or value.endswith((".SZ", ".SS", ".SH")):
        local = current.astimezone(SHANGHAI)
        sessions = ((time(9, 30), time(11, 30)), (time(13), time(15)))
    elif value:
        local = current.astimezone(NEW_YORK)
        if local.weekday() >= 5:
            return "closed"
        local_time = local.time().replace(tzinfo=None)
        if _within(local_time, time(4), time(9, 30)):
            return "premarket"
        if _within(local_time, time(9, 30), time(16)):
            return "regular"
        if _within(local_time, time(16), time(20)):
            return "afterhours"
        return "closed"
    else:
        return "unknown"

    if local.weekday() >= 5:
        return "closed"
    local_time = local.time().replace(tzinfo=None)
    return "regular" if any(_within(local_time, start, end) for start, end in sessions) else "closed"


def enabled_sessions_at(settings: dict[str, Any], now: datetime | None = None) -> list[str]:
    enabled: list[str] = []
    for session in market_sessions_at(now):
        if session == "us_premarket" and settings["analyze_us_premarket"]:
            enabled.append(session)
        elif session in {"cn_regular", "hk_regular", "us_regular"} and settings["analyze_regular_session"]:
            enabled.append(session)
        elif session == "us_afterhours" and settings["analyze_us_afterhours"]:
            enabled.append(session)
    return enabled


def schedule_status(
    settings: dict[str, Any],
    *,
    last_analysis_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _aware_utc(now)
    active = market_sessions_at(current)
    enabled = enabled_sessions_at(settings, current)
    interval = timedelta(minutes=int(settings["interval_minutes"]))
    normalized_last = _aware_utc(last_analysis_at) if last_analysis_at else None
    next_due_at = normalized_last + interval if normalized_last else None
    due = bool(enabled) and (next_due_at is None or current >= next_due_at)
    return {
        "current_sessions": [SESSION_LABELS[item] for item in active],
        "enabled_current_sessions": [SESSION_LABELS[item] for item in enabled],
        "last_analysis_at": normalized_last.isoformat() if normalized_last else None,
        "next_due_at": next_due_at.isoformat() if next_due_at else None,
        "due": due,
        "dispatcher_interval_minutes": 5,
    }


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _within(value: time, start: time, end: time) -> bool:
    return start <= value < end

from __future__ import annotations

from typing import Any, Protocol

from .llm import classify_security_themes


THEME_TAXONOMY: tuple[str, ...] = (
    "AI 半导体与存储",
    "AI 半导体与互连",
    "AI 平台与云服务",
    "AI 电力、楼宇与冷却",
    "新能源汽车",
    "消费电子",
    "企业软件与数字化",
    "资源与矿业",
    "光伏与清洁能源",
    "宽基指数",
    "衍生品",
    "其他",
)

BUILTIN_SECURITY_THEMES: dict[str, str] = {
    "SPY": "宽基指数",
    "AAPL": "消费电子",
    "MSFT": "AI 平台与云服务",
    "NVDA": "AI 半导体与存储",
}

LEGACY_THEME_LABELS: dict[str, str] = {
    "ai_semiconductor_storage": "AI 半导体与存储",
    "large_cap_ai_platform": "AI 平台与云服务",
    "ai_power_building_cooling": "AI 电力、楼宇与冷却",
    "ev": "新能源汽车",
    "consumer_electronics": "消费电子",
    "broad_market_index": "宽基指数",
    "derivative": "衍生品",
    "solar_cyclical": "光伏与清洁能源",
    "china_resources_mining": "资源与矿业",
}


class ThemeStore(Protocol):
    def security_themes(self) -> dict[str, dict[str, Any]]: ...

    def upsert_security_themes(self, themes: dict[str, str], *, source: str) -> None: ...


def normalize_theme(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in THEME_TAXONOMY:
        return text
    return LEGACY_THEME_LABELS.get(text.lower())


def resolve_security_themes(
    holdings: list[dict[str, Any]],
    stored: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    stored = stored or {}
    resolved: dict[str, str] = {}
    for holding in holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        stored_theme = normalize_theme(stored.get(symbol, {}).get("theme"))
        snapshot_theme = normalize_theme(holding.get("theme"))
        resolved[symbol] = stored_theme or snapshot_theme or BUILTIN_SECURITY_THEMES.get(symbol) or "未分类"
    return resolved


def ensure_security_themes(store: ThemeStore, holdings: list[dict[str, Any]]) -> dict[str, str]:
    stored = store.security_themes()
    resolved = resolve_security_themes(holdings, stored)

    snapshot_themes: dict[str, str] = {}
    builtin_themes: dict[str, str] = {}
    unknown: list[dict[str, str]] = []
    for holding in holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol or normalize_theme(stored.get(symbol, {}).get("theme")):
            continue
        snapshot_theme = normalize_theme(holding.get("theme"))
        if snapshot_theme:
            snapshot_themes[symbol] = snapshot_theme
        elif symbol in BUILTIN_SECURITY_THEMES:
            builtin_themes[symbol] = BUILTIN_SECURITY_THEMES[symbol]
        else:
            unknown.append(
                {
                    "symbol": symbol,
                    "name": str(holding.get("name") or symbol),
                    "market": str(holding.get("market") or ""),
                    "security_type": str(holding.get("security_type") or "stock"),
                }
            )

    store.upsert_security_themes(snapshot_themes, source="confirmed_snapshot")
    store.upsert_security_themes(builtin_themes, source="built_in")
    model_themes = classify_security_themes(unknown, THEME_TAXONOMY)
    store.upsert_security_themes(model_themes, source="model_api")

    return resolve_security_themes(holdings, store.security_themes())

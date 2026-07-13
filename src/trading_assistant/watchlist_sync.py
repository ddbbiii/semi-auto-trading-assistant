from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import re
import sys
from typing import Any

from .db import Store


KNOWN_INSTRUMENTS = {
    "SPY": ("SPDR S&P 500 ETF Trust", "US"),
    "AAPL": ("Apple", "US"),
    "MSFT": ("Microsoft", "US"),
    "NVDA": ("NVIDIA", "US"),
}


def parse_active_watchlist(markdown: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^###\s+.+Active Watchlist\s*$", line.strip(), re.IGNORECASE)
    ]
    if not headings:
        raise ValueError("finance.md 中没有找到 `### ... Active Watchlist` 小节。")
    start = headings[-1] + 1
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("### ")), len(lines))

    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in lines[start:end]:
        line = raw_line.strip()
        match = re.match(r"^-\s+`([^`]+)`\s*:\s*(.+)$", line)
        if match:
            if current:
                entries.append(current)
            symbol = match.group(1).strip().upper()
            name, market = KNOWN_INSTRUMENTS.get(symbol, (symbol, _market_for(symbol)))
            current = {
                "symbol": symbol,
                "name": name,
                "market": market,
                "thesis": match.group(2).strip(),
            }
        elif current and line and not line.startswith("-"):
            current["thesis"] = f"{current['thesis']} {line}"
    if current:
        entries.append(current)
    return validate_watchlist(entries)


def validate_watchlist(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not items:
        raise ValueError("Active Watchlist 为空，拒绝覆盖云端机会清单。")
    if len(items) > 30:
        raise ValueError("Active Watchlist 最多允许 30 个标的。")
    validated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9.-]{1,16}", symbol):
            raise ValueError(f"无效证券代码：{symbol or '<empty>'}")
        if symbol in seen:
            raise ValueError(f"Active Watchlist 包含重复代码：{symbol}")
        market = str(item.get("market") or _market_for(symbol)).upper()
        if market not in {"US", "HK", "CN"}:
            raise ValueError(f"{symbol} 的市场无效：{market}")
        thesis = str(item.get("thesis") or "").strip()
        if not thesis:
            raise ValueError(f"{symbol} 缺少关注理由。")
        validated.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or KNOWN_INSTRUMENTS.get(symbol, (symbol, market))[0]).strip(),
                "market": market,
                "thesis": thesis,
            }
        )
        seen.add(symbol)
    return validated


def _market_for(symbol: str) -> str:
    if symbol.endswith(".HK"):
        return "HK"
    if symbol.endswith((".SZ", ".SH", ".SS")) or symbol.isdigit():
        return "CN"
    return "US"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-assistant-watchlist")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--source", required=True)
    export_parser.add_argument("--base64", action="store_true")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--stdin", action="store_true", required=True)
    apply_parser.add_argument("--source", default="finance.md-active-watchlist")
    args = parser.parse_args(argv)

    if args.command == "export":
        items = parse_active_watchlist(Path(args.source).read_text(encoding="utf-8"))
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        print(base64.b64encode(payload.encode("utf-8")).decode("ascii") if args.base64 else payload)
        return 0

    items = validate_watchlist(json.loads(sys.stdin.read()))
    store = Store()
    store.replace_opportunity_watchlist(items, source=args.source)
    print(json.dumps({"status": "synced", "count": len(items), "symbols": [item["symbol"] for item in items]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

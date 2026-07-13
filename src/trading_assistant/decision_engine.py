from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .analysis_schedule import market_session_for_symbol
from .schemas import DataQuality, Decision, Evidence, OrderDraft


EXECUTION_QUOTE_MAX_AGE_SECONDS = 2 * 60
MONITORING_QUOTE_MAX_AGE_SECONDS = 30 * 60
CLOSED_MARKET_REFERENCE_MAX_AGE_SECONDS = 4 * 24 * 60 * 60
DEFAULT_RISK_SETTINGS: dict[str, float | int] = {
    "max_single_position_percent": 25.0,
    "daily_move_alert_percent": 8.0,
    "warrant_expiry_warning_days": 30,
    "target_weight_tolerance_percent": 2.0,
}
DEFAULT_WATCHLIST = (
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US", "thesis": "示例：宽基市场趋势观察"},
    {"symbol": "AAPL", "name": "Apple", "market": "US", "thesis": "示例：大型科技公司基本面观察"},
    {"symbol": "MSFT", "name": "Microsoft", "market": "US", "thesis": "示例：云计算与软件平台观察"},
)
OPPORTUNITY_THESIS_ZH = {
    "SPY": "公开版本的宽基示例，不代表任何真实关注列表或投资建议。",
    "AAPL": "公开版本的大型科技股示例，用于演示机会卡片和证据展开。",
    "MSFT": "公开版本的软件平台示例，用于演示可配置观察列表。",
}


def build_decisions(
    snapshot: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    *,
    risk_settings: dict[str, Any] | None = None,
    risk_profiles: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[Decision]:
    now = now or datetime.now(timezone.utc)
    settings = DEFAULT_RISK_SETTINGS | (risk_settings or {})
    as_of = _datetime(snapshot.get("as_of"))
    snapshot_age = max(0, int((now - as_of).total_seconds()))
    snapshot_fresh = snapshot_age <= 24 * 60 * 60
    holdings = [item for item in snapshot.get("holdings", []) if float(item.get("quantity") or 0) > 0]

    if not snapshot_fresh:
        return [
            _decision(
                now=now,
                symbol="PORTFOLIO",
                name="全部账户",
                title="先同步账户，再重新计算风险",
                summary=f"当前持仓快照已超过 24 小时（约 {snapshot_age // 3600} 小时），所有个股数量建议已锁定。",
                action="verify",
                priority="urgent",
                trigger="导入并确认最新账户快照后，系统会自动重新检查全部持仓。",
                invalid_if="持仓、现金或未成交订单仍未同步时，不生成具体数量建议。",
                confidence="high",
                quality=DataQuality(
                    provider=str(snapshot.get("source") or "snapshot"),
                    observed_at=as_of,
                    freshness_seconds=snapshot_age,
                    source_type="snapshot",
                    actionable=False,
                    issues=["portfolio_snapshot_stale"],
                ),
                evidence=[Evidence(kind="position", title="持仓快照过期", detail=as_of.isoformat(), observed_at=as_of)],
            )
        ]

    total_cny = _portfolio_value_cny({**snapshot, "holdings": holdings})
    profiles = {
        str(item["symbol"]).upper(): item
        for item in risk_profiles or []
        if item.get("status", "active") == "active"
    }
    candidates: list[Decision] = []
    max_weight = float(settings["max_single_position_percent"])
    move_threshold = float(settings["daily_move_alert_percent"])
    expiry_warning_days = int(settings["warrant_expiry_warning_days"])
    target_tolerance = float(settings["target_weight_tolerance_percent"])

    for holding in holdings:
        symbol = str(holding["symbol"]).upper()
        name = str(holding.get("name") or symbol)
        quote = quotes.get(symbol, {})
        quality = quote_quality(quote, now=now, snapshot_fresh=True, symbol=symbol)
        profile = profiles.get(symbol, {})
        current_weight = _holding_weight_cny(holding, total_cny)
        thesis_evidence = _thesis_evidence(profile)

        if current_weight is not None and current_weight > max_weight:
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 单一持仓集中度偏高",
                    summary=f"当前估算仓位 {current_weight:.2f}%，超过你设置的 {max_weight:.2f}% 集中度提醒线。",
                    action="reduce",
                    priority="high",
                    current_weight=current_weight,
                    target_weight=max_weight,
                    trigger=f"确认账户快照与主题敞口后，再决定是否将仓位降到 {max_weight:.2f}% 以下。",
                    invalid_if="总资产、现金或其他账户持仓尚未同步时，只作为集中度提醒，不计算减仓数量。",
                    confidence="high",
                    quality=_snapshot_quality(snapshot, as_of, snapshot_age),
                    evidence=[Evidence(kind="position", title="通用集中度规则", detail=f"{current_weight:.2f}% > {max_weight:.2f}%", observed_at=as_of), *thesis_evidence],
                )
            )

        change_percent = _number(quote.get("change_percent"))
        if quality.actionable and change_percent is not None and abs(change_percent) >= move_threshold:
            direction = "上涨" if change_percent > 0 else "下跌"
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 当日{direction}幅度异常",
                    summary=f"API 行情显示当前变动 {change_percent:+.2f}%，超过你设置的 {move_threshold:.2f}% 异常波动线。",
                    action="watch",
                    priority="high",
                    current_weight=current_weight,
                    trigger="核对公告、成交量和市场整体变化，确认是否出现影响原投资逻辑的新信息。",
                    invalid_if="行情源异常、复权口径变化或市场整体同步波动时，不单凭涨跌幅采取动作。",
                    confidence="medium",
                    quality=quality,
                    evidence=[Evidence(kind="price", title="通用异常波动规则", detail=f"{change_percent:+.2f}%；阈值 ±{move_threshold:.2f}%", observed_at=quality.observed_at), *thesis_evidence],
                )
            )

        expiry = _profile_expiry(profile, holding)
        if str(holding.get("security_type") or "").lower() in {"warrant", "cbbc"} and expiry:
            days_left = (expiry - now.date()).days
            if days_left <= expiry_warning_days:
                candidates.append(
                    _decision(
                        now=now,
                        symbol=symbol,
                        name=name,
                        title=f"{name} 距到期日仅剩 {max(days_left, 0)} 天",
                        summary=f"该衍生品到期日为 {expiry.isoformat()}，已进入你设置的 {expiry_warning_days} 天预警窗口。",
                        action="verify",
                        priority="urgent" if days_left <= 7 else "high",
                        current_weight=current_weight,
                        trigger="复核最后交易日、条款、流动性和时间价值，再决定是否继续持有。",
                        invalid_if="到期日或产品条款尚未由券商页面确认时，不生成具体退出价格。",
                        confidence="high",
                        quality=_snapshot_quality(snapshot, as_of, snapshot_age),
                        evidence=[Evidence(kind="risk_rule", title="通用到期预警", detail=f"到期日 {expiry.isoformat()}；剩余 {days_left} 天"), *thesis_evidence],
                    )
                )

        stop_price = _number(profile.get("stop_price"))
        current_price = _number(quote.get("price"))
        if stop_price is not None and quality.actionable and current_price is not None and current_price <= stop_price:
            quantity = float(holding.get("quantity") or 0)
            quantity_delta = -quantity if quality.execution_ready else None
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 已触及你确认的风险线",
                    summary=f"最近可用价 {current_price:.3f} 不高于你设置的 {stop_price:.3f}。该阈值来自用户规则，不是模型生成。",
                    action="exit",
                    priority="urgent",
                    current_weight=current_weight,
                    target_weight=0,
                    quantity_delta=quantity_delta,
                    trigger=f"复核最新可成交价仍不高于 {stop_price:.3f} 后，再决定是否执行退出。",
                    invalid_if="报价失真、产品条款变化或你已修改投资计划时，先更新规则再操作。",
                    confidence="high",
                    quality=quality,
                    evidence=[Evidence(kind="risk_rule", title="用户确认风险线", detail=f"最新价 {current_price:.3f} ≤ {stop_price:.3f}", observed_at=quality.observed_at), *thesis_evidence],
                    order=_exit_order(symbol, quantity, quote, now) if quality.execution_ready else None,
                )
            )

        target_weight = _number(profile.get("target_weight_percent"))
        if target_weight is not None and current_weight is not None and abs(current_weight - target_weight) >= target_tolerance:
            reducing = current_weight > target_weight
            quantity_delta = _target_quantity_delta(holding, quote, total_cny, target_weight) if quality.execution_ready else None
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 偏离你设置的目标仓位",
                    summary=f"当前估算仓位 {current_weight:.2f}%，目标 {target_weight:.2f}%，偏离超过 {target_tolerance:.2f} 个百分点。",
                    action="reduce" if reducing else "add",
                    priority="normal",
                    current_weight=current_weight,
                    target_weight=target_weight,
                    quantity_delta=quantity_delta,
                    trigger="确认账户总资产、可用数量和最新价格后，再生成或复核调仓草案。",
                    invalid_if="目标仓位、账户规模或投资逻辑已变化时，先修改用户规则。",
                    confidence="high",
                    quality=quality,
                    evidence=[Evidence(kind="risk_rule", title="用户确认目标仓位", detail=f"当前 {current_weight:.2f}%；目标 {target_weight:.2f}%"), *thesis_evidence],
                )
            )

    priority_order = {"urgent": 0, "high": 1, "normal": 2, "opportunity": 3}
    action_order = {"exit": 0, "reduce": 1, "verify": 2, "watch": 3, "add": 4, "hold": 5}
    ordered = sorted(candidates, key=lambda item: (priority_order[item.priority], action_order[item.action], item.symbol))
    selected: list[Decision] = []
    seen_symbols: set[str] = set()
    for item in ordered:
        if item.symbol in seen_symbols:
            continue
        selected.append(item)
        seen_symbols.add(item.symbol)
        if len(selected) == 3:
            break
    return selected


def build_opportunities(
    quotes: dict[str, dict[str, Any]],
    *,
    watchlist: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    results = []
    for item in watchlist or DEFAULT_WATCHLIST:
        symbol = str(item["symbol"]).upper()
        quote = quotes.get(symbol, {})
        quality = quote_quality(quote, now=now, snapshot_fresh=True, symbol=symbol)
        results.append(
            {
                **item,
                "thesis": OPPORTUNITY_THESIS_ZH.get(symbol, str(item.get("thesis") or "等待补充关注逻辑。")),
                "price": quote.get("price"),
                "regular_price": quote.get("regular_price"),
                "market_session": quote.get("market_session"),
                "change_percent": quote.get("change_percent"),
                "status": _opportunity_status(quality.actionable, quote.get("market_session")),
                "data_quality": quality.model_dump(mode="json"),
                "trend_30": [],
                "trend_90": [],
            }
        )
    return results


def quote_quality(
    quote: dict[str, Any],
    *,
    now: datetime,
    snapshot_fresh: bool,
    symbol: str | None = None,
) -> DataQuality:
    observed = _datetime_or_none(quote.get("observed_at") or quote.get("fetched_at"))
    freshness = int((now - observed).total_seconds()) if observed else None
    market_session = str(quote.get("market_session") or market_session_for_symbol(symbol or str(quote.get("symbol") or ""), now))
    market_status = "open" if market_session in {"premarket", "regular", "afterhours"} else "closed" if market_session == "closed" else "unknown"
    extended_session = market_session in {"premarket", "afterhours"}
    live = quote.get("status") == "live" and _number(quote.get("price")) is not None and float(quote["price"]) > 0
    issues: list[str] = []
    monitoring_ready = live and freshness is not None
    if not live:
        issues.append("live_quote_unavailable")
        monitoring_ready = False
    elif freshness is None:
        issues.append("quote_stale")
        monitoring_ready = False
    elif market_status == "open" and freshness > MONITORING_QUOTE_MAX_AGE_SECONDS:
        issues.append("quote_stale")
        monitoring_ready = False
    elif market_status == "open" and freshness > EXECUTION_QUOTE_MAX_AGE_SECONDS:
        issues.append("quote_delayed")
    elif market_status == "closed" and freshness > CLOSED_MARKET_REFERENCE_MAX_AGE_SECONDS:
        issues.append("quote_stale")
        monitoring_ready = False
    elif market_status == "closed":
        issues.append("market_closed_reference")
    if extended_session and quote.get("price_session") != market_session:
        issues.append("extended_quote_unavailable")
        monitoring_ready = False
    if not snapshot_fresh:
        issues.append("portfolio_snapshot_stale")
        monitoring_ready = False
    has_two_sided_quote = all(_number(quote.get(key)) is not None and float(quote[key]) > 0 for key in ("bid", "ask"))
    execution_ready = bool(
        monitoring_ready
        and market_status == "open"
        and not extended_session
        and freshness is not None
        and freshness <= EXECUTION_QUOTE_MAX_AGE_SECONDS
        and has_two_sided_quote
    )
    if monitoring_ready and extended_session:
        issues.append("extended_hours_monitoring")
    elif monitoring_ready and market_status == "open" and not execution_ready:
        issues.append("two_sided_quote_unavailable")
    usage = "execution" if execution_ready else "monitoring" if monitoring_ready and market_status == "open" else "reference" if monitoring_ready else "unavailable"
    return DataQuality(
        provider=str(quote.get("provider") or "unavailable"),
        observed_at=observed,
        freshness_seconds=freshness,
        source_type="live" if usage in ("execution", "monitoring") else "fallback" if usage == "reference" else "unavailable",
        actionable=monitoring_ready,
        usage=usage,
        market_status=market_status,
        execution_ready=execution_ready,
        issues=list(dict.fromkeys(issues)),
    )


def _snapshot_quality(snapshot: dict[str, Any], as_of: datetime, age: int) -> DataQuality:
    return DataQuality(
        provider=str(snapshot.get("source") or "portfolio_snapshot"),
        observed_at=as_of,
        freshness_seconds=age,
        source_type="derived",
        actionable=True,
        usage="monitoring",
        market_status="unknown",
        execution_ready=False,
        issues=[],
    )


def _profile_expiry(profile: dict[str, Any], holding: dict[str, Any]) -> date | None:
    value = profile.get("expiry_date") or (holding.get("terms") or {}).get("maturity")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _thesis_evidence(profile: dict[str, Any]) -> list[Evidence]:
    text = str(profile.get("thesis_invalidation") or "").strip()
    if not text:
        return []
    return [Evidence(kind="risk_rule", title="用户记录的投资逻辑失效条件", detail=text)]


def _exit_order(symbol: str, quantity: float, quote: dict[str, Any], now: datetime) -> OrderDraft | None:
    bid = _number(quote.get("bid"))
    if bid is None or bid <= 0 or quantity <= 0:
        return None
    return OrderDraft(
        symbol=symbol,
        side="sell",
        quantity=quantity,
        limit_price_low=round(bid * 0.98, 3),
        limit_price_high=round(bid, 3),
        valid_until=now + timedelta(minutes=10),
        executable=False,
    )


def _target_quantity_delta(holding: dict[str, Any], quote: dict[str, Any], total_cny: float, target: float) -> float | None:
    price = _number(quote.get("price"))
    if price is None or price <= 0:
        return None
    rates = {"CNY": 1.0, "HKD": 0.92, "USD": 7.2}
    rate = rates.get(str(holding.get("currency")), 1.0)
    current_value_cny = float(holding.get("live_market_value") or holding.get("market_value") or 0) * rate
    target_value_cny = total_cny * target / 100
    return round((target_value_cny - current_value_cny) / rate / price, 4)


def _opportunity_status(actionable: bool, market_session: Any) -> str:
    if not actionable:
        return "等待可靠行情"
    return {
        "premarket": "盘前行情观察",
        "afterhours": "盘后行情观察",
        "regular": "等待价格与趋势条件",
    }.get(str(market_session), "等待价格与趋势条件")


def _decision(
    *,
    now: datetime,
    symbol: str,
    name: str,
    title: str,
    summary: str,
    action: str,
    priority: str,
    trigger: str,
    invalid_if: str,
    confidence: str,
    quality: DataQuality,
    evidence: list[Evidence],
    current_weight: float | None = None,
    target_weight: float | None = None,
    quantity_delta: float | None = None,
    order: OrderDraft | None = None,
) -> Decision:
    return Decision(
        id=f"{now:%Y%m%d%H%M}-{symbol}-{uuid4().hex[:8]}",
        symbol=symbol,
        name=name,
        title=title,
        summary=summary,
        action=action,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        current_weight_percent=current_weight,
        target_weight_percent=target_weight,
        quantity_delta=quantity_delta,
        trigger=trigger,
        invalid_if=invalid_if,
        confidence=confidence,  # type: ignore[arg-type]
        data_quality=quality,
        evidence=evidence,
        order_draft=order,
        generated_at=now,
        expires_at=now + timedelta(hours=8),
    )


def _portfolio_value_cny(snapshot: dict[str, Any]) -> float:
    rates = {"CNY": 1.0, "HKD": 0.92, "USD": 7.2}
    return sum(
        float(holding.get("live_market_value") or holding.get("market_value") or 0)
        * rates.get(str(holding.get("currency")), 1.0)
        for holding in snapshot.get("holdings", [])
    )


def _holding_weight_cny(holding: dict[str, Any], total_cny: float) -> float | None:
    if total_cny <= 0:
        return None
    rates = {"CNY": 1.0, "HKD": 0.92, "USD": 7.2}
    value = float(holding.get("live_market_value") or holding.get("market_value") or 0)
    return round(value * rates.get(str(holding.get("currency")), 1.0) / total_cny * 100, 2)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime:
    parsed = _datetime_or_none(value)
    return parsed or datetime.fromtimestamp(0, timezone.utc)


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

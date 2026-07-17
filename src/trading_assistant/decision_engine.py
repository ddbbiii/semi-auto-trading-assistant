from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .analysis_schedule import market_session_for_symbol
from .fx import DEFAULT_RATES_TO_CNY
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
    official_evidence_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    rates_to_cny: dict[str, float] | None = None,
    now: datetime | None = None,
) -> list[Decision]:
    now = now or datetime.now(timezone.utc)
    settings = DEFAULT_RISK_SETTINGS | (risk_settings or {})
    as_of = _datetime(snapshot.get("as_of"))
    snapshot_age = max(0, int((now - as_of).total_seconds()))
    holdings = [item for item in snapshot.get("holdings", []) if float(item.get("quantity") or 0) > 0]

    rates = DEFAULT_RATES_TO_CNY | (rates_to_cny or {})
    total_cny = _portfolio_value_cny({**snapshot, "holdings": holdings}, rates)
    account_value_cny = _account_value_cny(snapshot.get("account") or {}, rates)
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
        quality = quote_quality(quote, now=now, symbol=symbol)
        profile = profiles.get(symbol, {})
        current_weight = _holding_weight_cny(holding, total_cny, rates)
        account_weight = _holding_weight_cny(holding, account_value_cny, rates) if account_value_cny else None
        thesis_evidence = _thesis_evidence(profile)
        official_evidence = _official_evidence((official_evidence_by_symbol or {}).get(symbol, []))
        profile_context = _profile_context(profile)

        if current_weight is not None and current_weight > max_weight:
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 持仓内权重偏高",
                    summary=f"当前持仓内权重 {current_weight:.2f}%，超过你设置的 {max_weight:.2f}% 集中度提醒线。",
                    action="verify",
                    priority="high",
                    current_weight=current_weight,
                    trigger="复核该标的对组合的风险贡献、波动、流动性、相关性、主题敞口和机会成本。",
                    invalid_if="若完整账户和相关敞口确认后风险贡献可接受，则不需要仅因名义仓位越线而减仓。",
                    current_limit="集中度提醒线不是目标仓位，不能单独生成减仓数量。",
                    policy_response="review",
                    confidence="high",
                    quality=_snapshot_quality(snapshot, as_of, snapshot_age),
                    evidence=[Evidence(kind="position", title="通用集中度规则", detail=f"{current_weight:.2f}% > {max_weight:.2f}%", observed_at=as_of), *thesis_evidence, *official_evidence],
                    **profile_context,
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
                    action="verify",
                    priority="high",
                    current_weight=current_weight,
                    trigger="核对公告、成交量和市场整体变化，确认是否出现影响原投资逻辑的新信息。",
                    invalid_if="行情源异常、复权口径变化或市场整体同步波动时，不单凭涨跌幅采取动作。",
                    current_limit="事件性质尚未归因；需要先区分价值事件、情绪流动性、混合因素或无法解释。",
                    policy_response="review",
                    event_classification="unexplained",
                    confidence="medium",
                    quality=quality,
                    evidence=[Evidence(kind="price", title="通用异常波动规则", detail=f"{change_percent:+.2f}%；阈值 ±{move_threshold:.2f}%", observed_at=quality.observed_at), *thesis_evidence, *official_evidence],
                    **profile_context,
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
                        current_limit="到期预警只说明时间约束增强，仍需核对条款、价差、正股和可交易性。",
                        policy_response="review",
                        confidence="high",
                        quality=_snapshot_quality(snapshot, as_of, snapshot_age),
                        evidence=[Evidence(kind="risk_rule", title="通用到期预警", detail=f"到期日 {expiry.isoformat()}；剩余 {days_left} 天"), *thesis_evidence, *official_evidence],
                        **profile_context,
                    )
                )

        stop_price = _number(profile.get("stop_price"))
        current_price = _number(quote.get("price"))
        if stop_price is not None and (not quality.actionable or current_price is None):
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 的价格风险线等待核验",
                    summary=f"你设置了 {stop_price:.3f} 的价格复核线，但当前没有足够新鲜的行情判断是否触发。",
                    action="verify",
                    priority="high",
                    current_weight=current_weight,
                    trigger="取得可靠行情，并按工具类型重新解释价格线。",
                    invalid_if="只有截图价、延迟价或无法确认交易时段时，本次核验不可操作。",
                    current_limit="数据不足，不能判断是否触线，更不能生成交易数量。",
                    policy_response="review",
                    confidence="medium",
                    quality=quality,
                    evidence=[Evidence(kind="risk_rule", title="用户确认价格复核线", detail=f"{stop_price:.3f}"), *thesis_evidence, *official_evidence],
                    **profile_context,
                )
            )
        elif stop_price is not None and current_price is not None and current_price <= stop_price:
            quantity = float(holding.get("quantity") or 0)
            available_quantity = _available_quantity(holding)
            security_type = str(holding.get("security_type") or "stock").lower()
            position_intent = str(profile.get("position_intent") or "long_term")
            configured_response = str(profile.get("price_response") or "review")
            hard_exit = security_type in {"warrant", "cbbc"} or (
                position_intent == "tactical" and configured_response == "exit"
            )
            response = "exit" if hard_exit else configured_response if configured_response in {"review", "stop_adding", "reduce"} else "review"
            action = "exit" if hard_exit else "reduce" if response == "reduce" else "verify"
            quantity_delta = -available_quantity if hard_exit and quality.execution_ready and available_quantity is not None else None
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 已触及用户确认的价格复核线",
                    summary=f"最近可用价 {current_price:.3f} 不高于 {stop_price:.3f}。系统按{_intent_label(position_intent)}语义处理，不把普通长期股票机械判定为清仓。",
                    action=action,
                    priority="urgent" if hard_exit else "high",
                    current_weight=current_weight,
                    target_weight=0 if hard_exit else None,
                    quantity_delta=quantity_delta,
                    trigger=f"确认最新价格仍不高于 {stop_price:.3f}，并复核公告、行业、资金面和投资论文。",
                    invalid_if=_exit_condition(profile) or "报价失真、事件归因未完成或投资计划已更新时，先修改规则。",
                    current_limit=(
                        "已确认硬退出语义，但可卖数量尚未同步；本次不生成具体数量或限价草案。"
                        if hard_exit and available_quantity is None
                        else "衍生品或已确认的战术价格止损允许硬退出；仍只生成草案。"
                        if hard_exit
                        else "长期股票的价格线只触发复核、暂停加仓或减仓检查，不自动清仓。"
                    ),
                    policy_response=response,
                    confidence="high",
                    quality=quality,
                    evidence=[Evidence(kind="risk_rule", title="用户确认价格复核线", detail=f"最新价 {current_price:.3f} ≤ {stop_price:.3f}", observed_at=quality.observed_at), *thesis_evidence, *official_evidence],
                    order=_exit_order(symbol, available_quantity, quote, now)
                    if hard_exit and quality.execution_ready and available_quantity is not None
                    else None,
                    **profile_context,
                )
            )

        target_weight = _number(profile.get("target_weight_percent"))
        if target_weight is not None and account_weight is not None and abs(account_weight - target_weight) >= target_tolerance:
            reducing = account_weight > target_weight
            condition = str(profile.get("reduce_conditions") if reducing else profile.get("buy_add_conditions") or "").strip()
            condition_ready = bool(condition) and quality.actionable
            quantity_delta = _target_quantity_delta(holding, quote, account_value_cny, target_weight, rates) if condition_ready and quality.execution_ready else None
            action = ("reduce" if reducing else "add") if condition_ready else "verify"
            candidates.append(
                _decision(
                    now=now,
                    symbol=symbol,
                    name=name,
                    title=f"{name} 偏离你设置的目标仓位",
                    summary=f"当前账户仓位 {account_weight:.2f}%，目标 {target_weight:.2f}%，偏离超过 {target_tolerance:.2f} 个百分点。",
                    action=action,
                    priority="normal",
                    current_weight=account_weight,
                    target_weight=target_weight,
                    quantity_delta=quantity_delta,
                    trigger=condition or ("先填写并确认减仓条件。" if reducing else "先填写并确认买入或加仓条件。"),
                    invalid_if=_exit_condition(profile) or "目标仓位、账户规模或投资论文变化时，先更新用户规则。",
                    current_limit=(
                        "条件已确认，但盘口未就绪，暂不计算具体数量。"
                        if condition and not quality.execution_ready
                        else "目标仓位偏离本身不是交易理由；缺少用户确认条件时只能核验。"
                        if not condition
                        else "行情不可用于当前判断，等待 API 恢复后再检查条件。"
                        if not quality.actionable
                        else "已满足规则前置条件；数量仅在账户和双边行情就绪时计算。"
                    ),
                    policy_response="reduce" if reducing and condition_ready else "review",
                    confidence="high",
                    quality=quality,
                    evidence=[Evidence(kind="risk_rule", title="用户确认目标仓位", detail=f"当前 {account_weight:.2f}%；目标 {target_weight:.2f}%"), *thesis_evidence, *official_evidence],
                    **profile_context,
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
        quality = quote_quality(quote, now=now, symbol=symbol)
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
    entries = (
        ("用户记录的投资论文", profile.get("thesis_summary")),
        ("信息等级", profile.get("information_grade") if profile.get("information_grade") != "unrated" else None),
        ("最强反方", profile.get("strongest_bear_case")),
        ("买入或加仓前置条件", profile.get("buy_add_conditions")),
        ("减仓条件", profile.get("reduce_conditions")),
        ("退出或失效条件", _exit_condition(profile)),
        ("悲观情景", profile.get("bear_scenario")),
        ("基准情景", profile.get("base_scenario")),
        ("乐观情景", profile.get("bull_scenario")),
    )
    return [
        Evidence(kind="risk_rule", title=title, detail=str(detail).strip())
        for title, detail in entries
        if str(detail or "").strip()
    ]


def _official_evidence(items: list[dict[str, Any]]) -> list[Evidence]:
    result: list[Evidence] = []
    for item in items[:3]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        kind = str(item.get("kind") or "filing")
        if kind not in {"filing", "news"}:
            kind = "filing"
        observed_at = item.get("observed_at")
        result.append(
            Evidence(
                kind=kind,
                title=title,
                detail=str(item.get("detail") or item.get("provider") or "官方披露来源"),
                source_url=str(item.get("source_url") or "") or None,
                observed_at=_datetime(observed_at) if observed_at else None,
            )
        )
    return result


def _exit_condition(profile: dict[str, Any]) -> str:
    return str(profile.get("exit_invalidation_conditions") or profile.get("thesis_invalidation") or "").strip()


def _profile_context(profile: dict[str, Any]) -> dict[str, str]:
    return {
        "information_grade": _choice(profile.get("information_grade"), {"A", "B", "C"}, "unrated"),
        "research_confidence": _choice(profile.get("research_confidence"), {"high", "medium", "low"}, "unrated"),
        "investment_certainty": _choice(profile.get("investment_certainty"), {"high", "medium", "low"}, "unrated"),
    }


def _choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or default)
    return text if text in allowed else default


def _intent_label(value: str) -> str:
    return {"long_term": "长期股票", "tactical": "战术交易", "derivative": "衍生品"}.get(value, "长期股票")


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


def _target_quantity_delta(
    holding: dict[str, Any],
    quote: dict[str, Any],
    total_cny: float,
    target: float,
    rates_to_cny: dict[str, float],
) -> float | None:
    price = _number(quote.get("price"))
    if price is None or price <= 0:
        return None
    rate = rates_to_cny.get(str(holding.get("currency")), 1.0)
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
    current_limit: str = "",
    policy_response: str = "review",
    event_classification: str = "not_applicable",
    information_grade: str = "unrated",
    research_confidence: str = "unrated",
    investment_certainty: str = "unrated",
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
        current_limit=current_limit,
        policy_response=policy_response,  # type: ignore[arg-type]
        event_classification=event_classification,  # type: ignore[arg-type]
        information_grade=information_grade,  # type: ignore[arg-type]
        research_confidence=research_confidence,  # type: ignore[arg-type]
        investment_certainty=investment_certainty,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        data_quality=quality,
        evidence=evidence,
        order_draft=order,
        generated_at=now,
        expires_at=now + timedelta(hours=8),
    )


def _portfolio_value_cny(snapshot: dict[str, Any], rates_to_cny: dict[str, float]) -> float:
    return sum(
        float(holding.get("live_market_value") or holding.get("market_value") or 0)
        * rates_to_cny.get(str(holding.get("currency")), 1.0)
        for holding in snapshot.get("holdings", [])
    )


def _holding_weight_cny(
    holding: dict[str, Any],
    total_cny: float,
    rates_to_cny: dict[str, float],
) -> float | None:
    if total_cny <= 0:
        return None
    value = float(holding.get("live_market_value") or holding.get("market_value") or 0)
    return round(value * rates_to_cny.get(str(holding.get("currency")), 1.0) / total_cny * 100, 2)


def _account_value_cny(account: dict[str, Any], rates_to_cny: dict[str, float]) -> float | None:
    for key in ("net_assets_cny", "account_value_cny", "total_equity_cny"):
        value = _number(account.get(key))
        if value is not None and value > 0:
            return value
    values: list[float] = []
    for currency in ("CNY", "HKD", "USD"):
        for prefix in ("net_assets", "account_value", "total_equity"):
            value = _number(account.get(f"{prefix}_{currency.lower()}"))
            if value is not None and value > 0:
                values.append(value * rates_to_cny.get(currency, 1.0))
                break
    return sum(values) if values else None


def _available_quantity(holding: dict[str, Any]) -> float | None:
    if holding.get("available_quantity") is None:
        return None
    available = _number(holding.get("available_quantity"))
    if available is None or available < 0:
        return None
    return min(available, float(holding.get("quantity") or 0))


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

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx


_STATUS_LOCK = Lock()
_LAST_ATTEMPT_AT: datetime | None = None
_LAST_SUCCESS_AT: datetime | None = None
_LAST_FAILURE_AT: datetime | None = None
_LAST_ERROR = ""
_LAST_HTTP_STATUS: int | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def status() -> dict[str, Any]:
    configured = all(
        os.getenv(name, "").strip()
        for name in ("TRADING_ASSISTANT_LLM_BASE_URL", "TRADING_ASSISTANT_LLM_API_KEY", "TRADING_ASSISTANT_LLM_MODEL")
    )
    with _STATUS_LOCK:
        last_attempt_at = _LAST_ATTEMPT_AT
        last_success_at = _LAST_SUCCESS_AT
        last_failure_at = _LAST_FAILURE_AT
        last_error = _LAST_ERROR
        last_http_status = _LAST_HTTP_STATUS

    if not configured:
        connection_status = "unknown"
        status_label = "not_configured"
        message = "大模型 API 尚未配置。"
    elif last_failure_at and (not last_success_at or last_failure_at > last_success_at):
        connection_status = "error"
        status_label = "configured"
        message = last_error or "大模型 API 最近一次调用失败。"
    elif last_success_at:
        connection_status = "ok"
        status_label = "configured"
        message = "大模型 API 最近一次调用成功。"
    else:
        connection_status = "unknown"
        status_label = "configured"
        message = "大模型 API 已配置，但尚未进行实际调用测试。"

    return {
        "status": status_label,
        "configured": configured,
        "connectivity": connection_status,
        "message": message,
        "model": os.getenv("TRADING_ASSISTANT_LLM_MODEL", ""),
        "api_style": os.getenv("TRADING_ASSISTANT_LLM_API_STYLE", "chat_completions"),
        "vision_import_enabled": os.getenv("TRADING_ASSISTANT_VISION_IMPORT_ENABLED", "0") == "1",
        "last_attempt_at": _iso(last_attempt_at),
        "last_success_at": _iso(last_success_at),
        "last_failure_at": _iso(last_failure_at),
        "last_http_status": last_http_status,
    }


def test_connection() -> dict[str, Any]:
    """Perform a harmless JSON request and return status without exposing the response."""
    if not status()["configured"]:
        return status() | {"test": "not_configured"}
    try:
        _request_json('只返回严格 JSON：{"ok":true}。不要添加其他内容。')
    except Exception:
        result = status()
        return result | {"test": "failed"}
    return status() | {"test": "passed"}


def enrich_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return enrich_decisions_with_status(decisions)[0]


def enrich_decisions_with_status(decisions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not decisions:
        return decisions, "skipped_no_decisions"
    enriched, model_status, _ = analyze_refresh_with_status(decisions, {"holdings": []})
    return enriched, model_status


def analyze_refresh_with_status(
    decisions: list[dict[str, Any]],
    portfolio_context: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str | None]:
    enriched, model_status, summary, _ = analyze_refresh_with_report(decisions, portfolio_context)
    return enriched, model_status, summary


def analyze_refresh_with_report(
    decisions: list[dict[str, Any]],
    portfolio_context: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str | None, dict[str, Any]]:
    """Run the model for a full refresh, even when deterministic rules found no actions."""
    if status()["status"] != "configured":
        summary = "大模型 API 尚未配置，本次仅完成本地规则复核。"
        return decisions, "skipped_not_configured", None, _fallback_analysis_report(
            decisions, portfolio_context, summary
        )
    sanitized = [
        {
            "id": item["id"],
            "symbol": item["symbol"],
            "name": item.get("name") or item["symbol"],
            "action": item["action"],
            "priority": item["priority"],
            "current_weight_percent": item.get("current_weight_percent"),
            "target_weight_percent": item.get("target_weight_percent"),
            "trigger": item["trigger"],
            "invalid_if": item["invalid_if"],
            "current_limit": item.get("current_limit", ""),
            "policy_response": item.get("policy_response", "review"),
            "event_classification": item.get("event_classification", "not_applicable"),
            "information_grade": item.get("information_grade", "unrated"),
            "research_confidence": item.get("research_confidence", "unrated"),
            "investment_certainty": item.get("investment_certainty", "unrated"),
            "evidence": [
                {
                    "kind": evidence["kind"],
                    "title": evidence["title"],
                    "detail": _humanize_internal_codes(evidence["detail"]),
                    "source_url": evidence.get("source_url"),
                }
                for evidence in item.get("evidence", [])
            ],
        }
        for item in decisions
    ]
    prompt = (
        "你是投资组合复核解释器。本地确定性规则已经完成，模型不得增加、删除或改变任何交易动作，"
        "也不得改变仓位、数量、价格、优先级或有效期。"
        "你需要复核本次脱敏的持仓与行情覆盖情况，并生成结构化的组合分析报告。区分事实、推断和限制，"
        "不使用账户总资产，不虚构新闻、公告、估值、价格或数据源。"
        "portfolio.data_coverage 是后端生成的权威覆盖说明：available 表示源数据存在，derived 表示本地已计算，"
        "partial 或 missing 才能描述为缺失；不得把仅保留在本地、未发送原始值的数据说成用户没有同步。"
        "portfolio.investment_policy 是适用于全部持仓的全局政策；逐标的 user_rule 仅是可选覆盖，缺少覆盖不得描述为投资逻辑缺失。"
        "official_evidence 只包含官方披露来源；不得把没有近期文件等同于来源未检查。"
        "invested_weight_percent 是已投资持仓内部权重，不等于包含现金的账户总仓位。"
        "如果存在决策，只为每条输入生成简短 title 和 summary。"
        "trigger、invalid_if、current_limit、policy_response、event_classification 和证据等级均由确定性规则锁定，不得改写。"
        "必须使用普通投资者能理解的简体中文，不得输出 quote_stale 等内部英文状态码。"
        "首次提及标的时使用‘证券名称（代码）’，不要只写证券代码；后续可简称证券名称。"
        "当 decisions 为空时，也必须完成复核并明确说明本次未触发动作，不得虚构建议。"
        "报告中的 tone 只能是 positive、neutral、warning、risk；逐标的 stance 仅用于解释，最终会由本地规则覆盖。"
        "返回 JSON 对象：{\"analysis_summary\":\"...\",\"analysis_report\":{"
        "\"headline\":\"一句话结论\",\"conclusion\":\"两到四句完整判断\","
        "\"market_facts\":[{\"label\":\"事实标签\",\"detail\":\"可核验事实\",\"tone\":\"neutral\"}],"
        "\"reasoning\":[{\"title\":\"判断标题\",\"detail\":\"从事实到结论的推理链\",\"tone\":\"warning\"}],"
        "\"position_notes\":[{\"symbol\":\"代码\",\"reason\":\"该标的当前为何这样处理\",\"tone\":\"neutral\"}],"
        "\"counterpoints\":[\"最强反方或可能推翻结论的条件\"],"
        "\"limitations\":[\"当前数据限制\"]},"
        "\"items\":[{\"id\":...,\"title\":...,\"summary\":...}]}。\n"
        + json.dumps(
            {"portfolio": portfolio_context, "decisions": sanitized},
            ensure_ascii=False,
        )
    )
    try:
        body = _request_json(prompt)
    except Exception:
        summary = "大模型 API 调用失败，本次仅展示本地规则复核结果。"
        return decisions, "failed_fallback", None, _fallback_analysis_report(
            decisions, portfolio_context, summary
        )
    generated = {
        item["id"]: item
        for item in body.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    analysis_summary = str(body.get("analysis_summary") or "").strip()
    if not analysis_summary:
        analysis_summary = (
            "模型已完成本次组合复核，确定性规则未触发需要处理的动作。"
            if not decisions
            else "模型已完成本次组合复核和决策解释。"
        )
    allowed = {"title", "summary"}
    enriched = [item | {key: value for key, value in generated.get(item["id"], {}).items() if key in allowed} for item in decisions]
    return (
        enriched,
        "used",
        analysis_summary,
        _normalize_analysis_report(body.get("analysis_report"), enriched, portfolio_context, analysis_summary),
    )


_REPORT_TONES = {"positive", "neutral", "warning", "risk"}
_ACTION_LABELS = {
    "verify": "先核验",
    "hold": "继续持有",
    "reduce": "复核减仓",
    "exit": "复核退出",
    "add": "满足条件后分批增加",
    "watch": "继续观察",
}
_ACTION_TONES = {
    "verify": "warning",
    "hold": "positive",
    "reduce": "risk",
    "exit": "risk",
    "add": "positive",
    "watch": "neutral",
}


def _normalize_analysis_report(
    value: Any,
    decisions: list[dict[str, Any]],
    portfolio_context: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    holdings = {
        str(item.get("symbol") or "").upper(): item
        for item in portfolio_context.get("holdings", [])
        if str(item.get("symbol") or "").strip()
    }
    decision_by_symbol = {str(item.get("symbol") or "").upper(): item for item in decisions}

    position_notes: list[dict[str, str]] = []
    seen: set[str] = set()
    for note in raw.get("position_notes", []):
        if not isinstance(note, dict):
            continue
        symbol = str(note.get("symbol") or "").upper()
        if symbol not in holdings or symbol in seen:
            continue
        holding = holdings[symbol]
        decision = decision_by_symbol.get(symbol)
        action = str(decision.get("action") or "watch") if decision else "watch"
        reason = _clean_text(note.get("reason"), 320)
        if not reason:
            continue
        position_notes.append(
            {
                "symbol": symbol,
                "name": _clean_text(holding.get("name") or symbol, 80),
                "stance": _ACTION_LABELS[action] if decision else "暂无动作",
                "reason": reason,
                "tone": _ACTION_TONES[action] if decision else _tone(note.get("tone")),
            }
        )
        seen.add(symbol)
    for symbol, decision in decision_by_symbol.items():
        if symbol in seen or symbol not in holdings:
            continue
        action = str(decision.get("action") or "verify")
        position_notes.append(
            {
                "symbol": symbol,
                "name": _clean_text(holdings[symbol].get("name") or symbol, 80),
                "stance": _ACTION_LABELS.get(action, "先核验"),
                "reason": _clean_text(decision.get("summary") or decision.get("trigger"), 320),
                "tone": _ACTION_TONES.get(action, "warning"),
            }
        )

    report = {
        "headline": _clean_text(raw.get("headline"), 100) or ("当前没有触发动作" if not decisions else "本次有事项需要复核"),
        "conclusion": _clean_text(raw.get("conclusion"), 700) or summary,
        "market_facts": _normalize_report_items(raw.get("market_facts"), label_key="label", limit=5),
        "reasoning": _normalize_report_items(raw.get("reasoning"), label_key="title", limit=6),
        "position_notes": position_notes[:12],
        "counterpoints": _normalize_text_list(raw.get("counterpoints"), 5),
        "limitations": _authoritative_limitations(portfolio_context)
        if portfolio_context.get("data_coverage")
        else _normalize_text_list(raw.get("limitations"), 5),
        "data_coverage": _normalize_data_coverage(portfolio_context.get("data_coverage")),
    }
    if not report["market_facts"] or not report["reasoning"]:
        fallback = _fallback_analysis_report(decisions, portfolio_context, summary)
        report["market_facts"] = report["market_facts"] or fallback["market_facts"]
        report["reasoning"] = report["reasoning"] or fallback["reasoning"]
        report["limitations"] = report["limitations"] or fallback["limitations"]
    return report


def _fallback_analysis_report(
    decisions: list[dict[str, Any]],
    portfolio_context: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    total = int(portfolio_context.get("holding_count") or len(portfolio_context.get("holdings", [])))
    live = int(portfolio_context.get("live_quote_count") or 0)
    fallback = max(0, total - live)
    return {
        "headline": "当前没有触发动作" if not decisions else f"有 {len(decisions)} 项需要复核",
        "conclusion": summary,
        "market_facts": [
            {
                "label": "行情覆盖",
                "detail": f"本次检查 {total} 个持仓，{live} 个取得有效行情，{fallback} 个使用参考或不可用数据。",
                "tone": "positive" if total > 0 and live == total else "warning",
            }
        ],
        "reasoning": [
            {
                "title": "本地规则结果",
                "detail": "确定性规则未触发需要处理的动作。" if not decisions else f"确定性规则触发 {len(decisions)} 项复核事项，模型无权改变这些动作。",
                "tone": "neutral" if not decisions else "warning",
            }
        ],
        "position_notes": [],
        "counterpoints": [],
        "limitations": (
            ["未完成模型解释时，只能展示行情覆盖和确定性规则结果。"]
            + _authoritative_limitations(portfolio_context)
        )[:6],
        "data_coverage": _normalize_data_coverage(portfolio_context.get("data_coverage")),
    }


def _normalize_data_coverage(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    allowed_statuses = {"available", "derived", "partial", "missing"}
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key"), 50)
        label = _clean_text(item.get("label"), 50)
        status = str(item.get("status") or "missing")
        if not key or not label or status not in allowed_statuses:
            continue
        result.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "available": max(0, int(item.get("available") or 0)),
                "total": max(0, int(item.get("total") or 0)),
                "detail": _clean_text(item.get("detail"), 240),
            }
        )
    return result[:16]


def _authoritative_limitations(portfolio_context: dict[str, Any]) -> list[str]:
    coverage = {
        str(item.get("key")): item
        for item in portfolio_context.get("data_coverage", [])
        if isinstance(item, dict)
    }
    limitations: list[str] = []

    account_weight = coverage.get("account_weight", {})
    if account_weight.get("status") in {"missing", "partial"}:
        limitations.append("尚未同步账户净资产和现金，当前权重仅表示已投资持仓内部占比，不能代表账户总仓位。")

    available_quantity = coverage.get("available_quantity", {})
    if available_quantity.get("status") in {"missing", "partial"}:
        limitations.append(
            f"可卖数量仅覆盖 {int(available_quantity.get('available') or 0)}/{int(available_quantity.get('total') or 0)} 个持仓；未覆盖标的不生成具体卖出数量。"
        )

    daily_change = coverage.get("daily_change", {})
    if daily_change.get("status") in {"missing", "partial"}:
        limitations.append(
            f"当日涨跌幅仅覆盖 {int(daily_change.get('available') or 0)}/{int(daily_change.get('total') or 0)} 个持仓，异常波动比较可能不完整。"
        )

    official_evidence = coverage.get("official_evidence", {})
    if official_evidence.get("status") in {"missing", "partial"}:
        limitations.append(
            f"官方公告与财报来源仅检查 {int(official_evidence.get('available') or 0)}/{int(official_evidence.get('total') or 0)} 个持仓；未覆盖标的不能据此判断基本面变化或催化剂。"
        )

    return limitations[:5]


def _normalize_report_items(value: Any, *, label_key: str, limit: int) -> list[dict[str, str]]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get(label_key), 80)
        detail = _clean_text(item.get("detail"), 420)
        if label and detail:
            result.append({label_key: label, "detail": detail, "tone": _tone(item.get("tone"))})
    return result[:limit]


def _normalize_text_list(value: Any, limit: int) -> list[str]:
    return [text for item in (value if isinstance(value, list) else []) if (text := _clean_text(item, 360))][:limit]


def _tone(value: Any) -> str:
    tone = str(value or "neutral")
    return tone if tone in _REPORT_TONES else "neutral"


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def classify_security_themes(
    securities: list[dict[str, Any]],
    allowed_themes: tuple[str, ...],
) -> dict[str, str]:
    if status()["status"] != "configured" or not securities:
        return {}
    sanitized = [
        {
            "symbol": str(item.get("symbol") or "").upper(),
            "name": str(item.get("name") or ""),
            "market": str(item.get("market") or ""),
            "security_type": str(item.get("security_type") or ""),
        }
        for item in securities
    ]
    prompt = (
        "你是证券投资主题分类器。请根据证券代码、名称、市场和证券类型，为每个标的选择一个最贴近的投资主题。"
        "只能从给定主题中选择，不得创造新类别。返回严格 JSON："
        '{"items":[{"symbol":"...","theme":"..."}]}。\n'
        f"可选主题：{json.dumps(allowed_themes, ensure_ascii=False)}\n"
        f"待分类标的：{json.dumps(sanitized, ensure_ascii=False)}"
    )
    try:
        body = _request_json(prompt)
    except Exception:
        return {}
    requested_symbols = {item["symbol"] for item in sanitized if item["symbol"]}
    allowed = set(allowed_themes)
    result: dict[str, str] = {}
    for item in body.get("items", []):
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        theme = str(item.get("theme") or "")
        if symbol in requested_symbols and theme in allowed:
            result[symbol] = theme
    return result


def _request_json(prompt: str) -> dict[str, Any]:
    if not status()["configured"]:
        raise RuntimeError("模型 API 尚未配置。")
    attempt_at = _now()
    with _STATUS_LOCK:
        global _LAST_ATTEMPT_AT
        _LAST_ATTEMPT_AT = attempt_at
    base_url = os.environ["TRADING_ASSISTANT_LLM_BASE_URL"].rstrip("/")
    api_style = os.getenv("TRADING_ASSISTANT_LLM_API_STYLE", "chat_completions")
    if api_style == "responses":
        endpoint = f"{base_url}/responses"
        payload = {"model": os.environ["TRADING_ASSISTANT_LLM_MODEL"], "input": prompt}
    else:
        endpoint = f"{base_url}/chat/completions"
        payload = {
            "model": os.environ["TRADING_ASSISTANT_LLM_MODEL"],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {os.environ['TRADING_ASSISTANT_LLM_API_KEY']}"},
            json=payload,
            timeout=httpx.Timeout(120, connect=15),
        )
        response.raise_for_status()
        body = response.json()
        content = _extract_responses_text(body) if api_style == "responses" else body["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_json_fence(content))
    except httpx.HTTPStatusError as exc:
        _record_failure(f"大模型 API 返回 HTTP {exc.response.status_code}。", exc.response.status_code)
        raise
    except httpx.TimeoutException:
        _record_failure("大模型 API 请求超时。", None)
        raise
    except httpx.RequestError:
        _record_failure("大模型 API 网络请求失败。", None)
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        _record_failure("大模型 API 返回格式无法解析。", None)
        raise
    except Exception:
        _record_failure("大模型 API 调用失败。", None)
        raise
    _record_success(response.status_code)
    return parsed


def _record_success(http_status: int | None) -> None:
    with _STATUS_LOCK:
        global _LAST_SUCCESS_AT, _LAST_ERROR, _LAST_HTTP_STATUS
        _LAST_SUCCESS_AT = _now()
        _LAST_ERROR = ""
        _LAST_HTTP_STATUS = http_status


def _record_failure(message: str, http_status: int | None) -> None:
    with _STATUS_LOCK:
        global _LAST_FAILURE_AT, _LAST_ERROR, _LAST_HTTP_STATUS
        _LAST_FAILURE_AT = _now()
        _LAST_ERROR = message
        _LAST_HTTP_STATUS = http_status


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_responses_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    parts = []
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    if not parts:
        raise ValueError("Responses API 未返回 output_text 内容。")
    return "".join(parts)


def _humanize_internal_codes(value: str) -> str:
    labels = {
        "quote_stale": "行情超过当前场景允许的监控时限，系统将通过 API 自动重试",
        "quote_delayed": "行情有短暂延迟，但仍可用于日常风险监控",
        "market_closed_reference": "当前已闭市，使用最近交易时段行情作为风险参考",
        "extended_hours_monitoring": "当前为美股盘前或盘后，行情仅用于观察，不生成具体限价草案",
        "extended_quote_unavailable": "行情接口暂未返回当前盘前或盘后价格，不能用正常收盘价替代",
        "two_sided_quote_unavailable": "暂未取得新鲜双边盘口，不生成具体限价草案",
        "live_quote_unavailable": "暂时无法取得可靠的实时行情",
        "quote_above_stop": "当前价格尚未触及风险线",
        "official_news_unverified": "最新官方公告和重要信息尚未完成核验",
    }
    return labels.get(value, value)

from __future__ import annotations

import json
import os
from typing import Any

import httpx


def status() -> dict[str, Any]:
    configured = all(
        os.getenv(name, "").strip()
        for name in ("TRADING_ASSISTANT_LLM_BASE_URL", "TRADING_ASSISTANT_LLM_API_KEY", "TRADING_ASSISTANT_LLM_MODEL")
    )
    return {
        "status": "configured" if configured else "not_configured",
        "model": os.getenv("TRADING_ASSISTANT_LLM_MODEL", ""),
        "api_style": os.getenv("TRADING_ASSISTANT_LLM_API_STYLE", "chat_completions"),
        "vision_import_enabled": os.getenv("TRADING_ASSISTANT_VISION_IMPORT_ENABLED", "0") == "1",
    }


def enrich_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return enrich_decisions_with_status(decisions)[0]


def enrich_decisions_with_status(decisions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not decisions:
        return decisions, "skipped_no_decisions"
    if status()["status"] != "configured":
        return decisions, "skipped_not_configured"
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
            "evidence": [
                {"kind": evidence["kind"], "title": evidence["title"], "detail": _humanize_internal_codes(evidence["detail"])}
                for evidence in item.get("evidence", [])
            ],
        }
        for item in decisions
    ]
    prompt = (
        "你是投资决策解释器。不得改变动作、仓位、数量、价格、优先级或有效期。"
        "只为每条输入生成简短 title、summary、trigger、invalid_if。区分事实和推断，不使用账户总资产。"
        "必须使用普通投资者能理解的简体中文，不得输出 quote_stale、portfolio_snapshot_stale 等内部英文状态码。"
        "首次提及标的时使用‘证券名称（代码）’，不要只写证券代码；后续可简称证券名称。"
        "当数据不可操作时，trigger 应说明恢复计算需要什么，invalid_if 应说明当前受什么限制。"
        "返回 JSON 对象：{\"items\":[{\"id\":...,\"title\":...,\"summary\":...,\"trigger\":...,\"invalid_if\":...}]}。\n"
        + json.dumps(sanitized, ensure_ascii=False)
    )
    try:
        generated = {item["id"]: item for item in _request_json(prompt).get("items", [])}
    except Exception:
        return decisions, "failed_fallback"
    allowed = {"title", "summary", "trigger", "invalid_if"}
    return (
        [item | {key: value for key, value in generated.get(item["id"], {}).items() if key in allowed} for item in decisions],
        "used",
    )


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
    if status()["status"] != "configured":
        raise RuntimeError("模型 API 尚未配置。")
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
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {os.environ['TRADING_ASSISTANT_LLM_API_KEY']}"},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    content = _extract_responses_text(body) if api_style == "responses" else body["choices"][0]["message"]["content"]
    return json.loads(_strip_json_fence(content))


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
        "portfolio_snapshot_stale": "账户持仓超过二十四小时未确认",
        "quote_above_stop": "当前价格尚未触及风险线",
        "official_news_unverified": "最新官方公告和重要信息尚未完成核验",
    }
    return labels.get(value, value)

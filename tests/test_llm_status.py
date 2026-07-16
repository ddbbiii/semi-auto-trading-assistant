from __future__ import annotations

import httpx

from trading_assistant import llm


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"output_text": '{"ok": true}'}


def reset_llm_state() -> None:
    llm._LAST_ATTEMPT_AT = None
    llm._LAST_SUCCESS_AT = None
    llm._LAST_FAILURE_AT = None
    llm._LAST_ERROR = ""
    llm._LAST_HTTP_STATUS = None


def configure_model(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_ASSISTANT_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("TRADING_ASSISTANT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("TRADING_ASSISTANT_LLM_MODEL", "test-model")
    monkeypatch.setenv("TRADING_ASSISTANT_LLM_API_STYLE", "responses")


def test_successful_model_call_updates_connectivity(monkeypatch) -> None:
    reset_llm_state()
    configure_model(monkeypatch)
    monkeypatch.setattr(llm.httpx, "post", lambda *args, **kwargs: FakeResponse())

    assert llm._request_json('{"test": true}') == {"ok": True}

    result = llm.status()
    assert result["status"] == "configured"
    assert result["connectivity"] == "ok"
    assert result["last_success_at"]
    assert result["last_http_status"] == 200


def test_http_failure_is_visible_in_status(monkeypatch) -> None:
    reset_llm_state()
    configure_model(monkeypatch)
    request = httpx.Request("POST", "https://example.test/v1/responses")
    response = httpx.Response(401, request=request)

    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(llm.httpx, "post", fail)

    try:
        llm._request_json('{"test": true}')
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected HTTPStatusError")

    result = llm.status()
    assert result["status"] == "configured"
    assert result["connectivity"] == "error"
    assert result["last_http_status"] == 401
    assert "HTTP 401" in result["message"]


def test_unconfigured_model_is_not_reported_as_failed(monkeypatch) -> None:
    reset_llm_state()
    for name in ("TRADING_ASSISTANT_LLM_BASE_URL", "TRADING_ASSISTANT_LLM_API_KEY", "TRADING_ASSISTANT_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    result = llm.test_connection()

    assert result["status"] == "not_configured"
    assert result["connectivity"] == "unknown"
    assert result["test"] == "not_configured"


def test_full_analysis_calls_model_when_no_decisions(monkeypatch) -> None:
    reset_llm_state()
    configure_model(monkeypatch)
    prompts: list[str] = []

    def request(prompt: str) -> dict[str, object]:
        prompts.append(prompt)
        return {"analysis_summary": "已复核全部持仓，本次没有触发需要处理的动作。", "items": []}

    monkeypatch.setattr(llm, "_request_json", request)

    decisions, model_status, summary = llm.analyze_refresh_with_status(
        [],
        {
            "analysis_mode": "full",
            "holding_count": 1,
            "holdings": [{"symbol": "TEST", "quote_status": "live"}],
        },
    )

    assert decisions == []
    assert model_status == "used"
    assert summary == "已复核全部持仓，本次没有触发需要处理的动作。"
    assert len(prompts) == 1
    assert '"symbol": "TEST"' in prompts[0]


def test_structured_report_keeps_deterministic_action_and_known_symbols(monkeypatch) -> None:
    reset_llm_state()
    configure_model(monkeypatch)

    def request(_prompt: str) -> dict[str, object]:
        return {
            "analysis_summary": "组合需要继续观察。",
            "analysis_report": {
                "headline": "保持耐心，先核验风险",
                "conclusion": "行情完整，但本地规则要求先核验测试标的。",
                "market_facts": [{"label": "行情", "detail": "报价有效。", "tone": "positive"}],
                "reasoning": [{"title": "规则优先", "detail": "先处理已触发事项。", "tone": "warning"}],
                "position_notes": [
                    {"symbol": "TEST", "stance": "模型擅自建议买入", "reason": "规则已触发核验。", "tone": "positive"},
                    {"symbol": "UNKNOWN", "reason": "不应出现在报告。", "tone": "risk"},
                ],
                "counterpoints": ["公告可能改变判断。"],
                "limitations": ["尚未接入完整公告。"],
            },
            "items": [],
        }

    monkeypatch.setattr(llm, "_request_json", request)
    decision = {
        "id": "decision-1",
        "symbol": "TEST",
        "name": "测试标的",
        "action": "verify",
        "priority": "high",
        "trigger": "核验行情",
        "invalid_if": "行情无效",
        "data_quality": {"actionable": False},
        "evidence": [],
    }

    enriched, model_status, summary, report = llm.analyze_refresh_with_report(
        [decision],
        {
            "analysis_mode": "full",
            "holding_count": 1,
            "live_quote_count": 1,
            "holdings": [{"symbol": "TEST", "name": "测试标的", "quote_status": "live"}],
        },
    )

    assert model_status == "used"
    assert summary == "组合需要继续观察。"
    assert enriched[0]["action"] == "verify"
    assert report["position_notes"] == [{
        "symbol": "TEST",
        "name": "测试标的",
        "stance": "先核验",
        "reason": "规则已触发核验。",
        "tone": "warning",
    }]

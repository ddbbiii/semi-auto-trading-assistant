from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import smtplib
import ssl
from typing import Any


@dataclass(frozen=True)
class EmailAlertConfig:
    enabled: bool
    recipient: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool

    @classmethod
    def from_env(cls) -> "EmailAlertConfig":
        return cls(
            enabled=os.getenv("TRADING_ASSISTANT_EMAIL_ALERTS", "0") == "1",
            recipient=os.getenv("TRADING_ASSISTANT_ALERT_EMAIL_TO", ""),
            smtp_host=os.getenv("TRADING_ASSISTANT_SMTP_HOST", ""),
            smtp_port=int(os.getenv("TRADING_ASSISTANT_SMTP_PORT", "587")),
            smtp_username=os.getenv("TRADING_ASSISTANT_SMTP_USERNAME", ""),
            smtp_password=os.getenv("TRADING_ASSISTANT_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("TRADING_ASSISTANT_SMTP_FROM", "")
            or os.getenv("TRADING_ASSISTANT_SMTP_USERNAME", ""),
            smtp_use_tls=os.getenv("TRADING_ASSISTANT_SMTP_USE_TLS", "1") != "0",
        )

    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing = []
        for field_name in (
            "recipient",
            "smtp_host",
            "smtp_username",
            "smtp_password",
            "smtp_from",
        ):
            if not getattr(self, field_name):
                missing.append(field_name)
        return tuple(missing)


def maybe_send_action_alert_email(
    monitoring_payload: dict[str, Any],
    *,
    state_path: str | Path = "data/runtime/email-alert-state.json",
    config: EmailAlertConfig | None = None,
) -> dict[str, Any]:
    config = config or EmailAlertConfig.from_env()
    action_rules = [
        rule
        for rule in monitoring_payload.get("rules", [])
        if rule.get("severity") == "urgent" and rule.get("status") != "resolved"
    ]

    if not action_rules:
        return {"status": "no_action", "action_count": 0}

    if not config.enabled:
        return {"status": "disabled", "action_count": len(action_rules)}

    if config.missing_fields:
        return {
            "status": "not_configured",
            "action_count": len(action_rules),
            "recipient": config.recipient,
            "missing_fields": list(config.missing_fields),
        }

    fingerprint = _alert_fingerprint(monitoring_payload, action_rules)
    state_file = Path(state_path)
    state = _read_state(state_file)
    if state.get("last_sent_fingerprint") == fingerprint:
        return {
            "status": "already_sent",
            "action_count": len(action_rules),
            "recipient": config.recipient,
            "last_sent_at": state.get("last_sent_at"),
        }

    subject = f"交易助手操作告警：{len(action_rules)} 个紧急检查项"
    body = _format_alert_body(monitoring_payload, action_rules)

    try:
        _send_email(config, subject, body)
    except Exception as exc:
        return {
            "status": "error",
            "action_count": len(action_rules),
            "recipient": config.recipient,
            "detail": str(exc),
        }

    sent_at = datetime.now(timezone.utc).isoformat()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "last_sent_fingerprint": fingerprint,
                "last_sent_at": sent_at,
                "recipient": config.recipient,
                "action_rule_ids": [rule.get("id") for rule in action_rules],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "status": "sent",
        "action_count": len(action_rules),
        "recipient": config.recipient,
        "sent_at": sent_at,
    }


def maybe_send_decision_alert_email(
    decisions: list[dict[str, Any]],
    *,
    state_path: str | Path = "data/runtime/decision-email-state.json",
    config: EmailAlertConfig | None = None,
) -> dict[str, Any]:
    config = config or EmailAlertConfig.from_env()
    urgent = [
        item
        for item in decisions
        if item.get("priority") == "urgent" and item.get("data_quality", {}).get("actionable") is True
    ]
    if not urgent:
        return {"status": "no_action", "action_count": 0}
    if not config.enabled:
        return {"status": "disabled", "action_count": len(urgent)}
    if config.missing_fields:
        return {
            "status": "not_configured",
            "action_count": len(urgent),
            "missing_fields": list(config.missing_fields),
        }

    fingerprint_payload = [
        {
            "symbol": item.get("symbol"),
            "action": item.get("action"),
            "trigger": item.get("trigger"),
            "observed_at": item.get("data_quality", {}).get("observed_at"),
        }
        for item in urgent
    ]
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    state_file = Path(state_path)
    state = _read_state(state_file)
    if state.get("last_sent_fingerprint") == fingerprint:
        return {"status": "already_sent", "action_count": len(urgent), "last_sent_at": state.get("last_sent_at")}

    lines = ["OpenStock 紧急决策提醒", ""]
    for index, item in enumerate(urgent, start=1):
        quality = item.get("data_quality", {})
        lines.extend(
            [
                f"{index}. {item.get('symbol')} · {item.get('title')}",
                f"   动作：{item.get('action')}",
                f"   触发：{item.get('trigger')}",
                f"   失效：{item.get('invalid_if')}",
                f"   数据：{quality.get('provider')} / {quality.get('observed_at')}",
                "",
            ]
        )
    lines.extend(["这是一条人工复核提醒，不是交易指令。", "系统不会自动下单；操作前请重新核对券商盘口与公告。"])
    try:
        _send_email(config, f"OpenStock：{len(urgent)} 个紧急决策待复核", "\n".join(lines))
    except Exception as exc:
        return {"status": "error", "action_count": len(urgent), "detail": str(exc)}

    sent_at = datetime.now(timezone.utc).isoformat()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"last_sent_fingerprint": fingerprint, "last_sent_at": sent_at}, indent=2),
        encoding="utf-8",
    )
    return {"status": "sent", "action_count": len(urgent), "sent_at": sent_at}


def _alert_fingerprint(
    monitoring_payload: dict[str, Any],
    action_rules: list[dict[str, Any]],
) -> str:
    normalized = {
        "as_of": monitoring_payload.get("as_of"),
        "rules": [
            {
                "id": rule.get("id"),
                "symbol": rule.get("symbol"),
                "status": rule.get("status"),
                "title": rule.get("title"),
            }
            for rule in action_rules
        ],
    }
    encoded = json.dumps(normalized, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _format_alert_body(
    monitoring_payload: dict[str, Any],
    action_rules: list[dict[str, Any]],
) -> str:
    account = monitoring_payload.get("account", {})
    lines = [
        "交易助手操作告警",
        "",
        f"时间：{monitoring_payload.get('as_of', '未知')}",
        f"资产净值：USD {account.get('net_assets_usd', '未知')}",
        f"现金购买力：USD {account.get('cash_buying_power_usd', '未知')}",
        f"未成交订单：{monitoring_payload.get('pending_order_count', '未知')}",
        "",
        "紧急检查项：",
    ]
    for index, rule in enumerate(action_rules, start=1):
        symbol = rule.get("symbol") or "portfolio"
        lines.extend(
            [
                f"{index}. {symbol} - {rule.get('title', '')}",
                f"   {rule.get('detail', '')}",
            ]
        )
    lines.extend(
        [
            "",
            "这是一条监控告警，不是交易指令。",
            "任何操作前都必须重新核验实时价格、新闻、公告和产品条款。",
        ]
    )
    return "\n".join(lines)


def _send_email(config: EmailAlertConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from
    message["To"] = config.recipient
    message.set_content(body)

    if config.smtp_use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as smtp:
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

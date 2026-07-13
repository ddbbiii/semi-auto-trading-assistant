from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_assistant.notifications import EmailAlertConfig, maybe_send_action_alert_email


def synthetic_alert_payload() -> dict[str, object]:
    return {
        "as_of": "2026-01-02T10:00:00+00:00",
        "account": {"net_assets_usd": 10000, "cash_buying_power_usd": 6000},
        "pending_order_count": 0,
        "rules": [
            {
                "id": "synthetic-risk-check",
                "symbol": "AAPL",
                "severity": "urgent",
                "status": "triggered",
                "title": "合成告警测试",
                "detail": "仅用于验证通知流程。",
            }
        ],
    }


class NotificationTests(unittest.TestCase):
    def test_reports_missing_smtp_config_without_sending(self) -> None:
        payload = synthetic_alert_payload()
        config = EmailAlertConfig(
            enabled=True,
            recipient="recipient@example.com",
            smtp_host="",
            smtp_port=587,
            smtp_username="",
            smtp_password="",
            smtp_from="",
            smtp_use_tls=True,
        )

        result = maybe_send_action_alert_email(payload, config=config)

        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(result["recipient"], "recipient@example.com")
        self.assertIn("smtp_host", result["missing_fields"])

    def test_deduplicates_sent_alert_state(self) -> None:
        payload = synthetic_alert_payload()
        config = EmailAlertConfig(
            enabled=True,
            recipient="user@example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="sender@example.com",
            smtp_password="secret",
            smtp_from="sender@example.com",
            smtp_use_tls=True,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "email-alert-state.json"
            with patch("trading_assistant.notifications._send_email") as send_email:
                first = maybe_send_action_alert_email(
                    payload,
                    state_path=state_path,
                    config=config,
                )
                second = maybe_send_action_alert_email(
                    payload,
                    state_path=state_path,
                    config=config,
                )

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "already_sent")
        send_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()

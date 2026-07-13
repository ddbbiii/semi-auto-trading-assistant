import unittest

from trading_assistant.api import build_demo_draft_payload, build_health_payload
from trading_assistant.market_data import normalize_finnhub_symbol
from trading_assistant.portfolio_state import get_monitoring_payload, get_portfolio_payload


class ApiPayloadTests(unittest.TestCase):
    def test_health_payload(self) -> None:
        payload = build_health_payload()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "semi-auto-trading-assistant-api")
        self.assertEqual(payload["broker"], "simulated")

    def test_demo_draft_payload(self) -> None:
        payload = build_demo_draft_payload()

        self.assertEqual(payload["draft"]["symbol"], "AAPL")
        self.assertEqual(payload["draft"]["side"], "buy")
        self.assertIs(payload["risk"]["allowed"], True)

    def test_portfolio_payload_uses_synthetic_demo(self) -> None:
        payload = get_portfolio_payload()
        by_symbol = {holding["symbol"]: holding for holding in payload["holdings"]}

        self.assertEqual(payload["source"], "bundled_synthetic_demo")
        self.assertEqual(payload["pending_order_count"], 0)
        self.assertEqual(payload["holding_count"], 3)
        self.assertEqual(set(by_symbol), {"AAPL", "MSFT", "SPY"})
        self.assertEqual(by_symbol["AAPL"]["quantity"], 5)
        self.assertEqual(by_symbol["MSFT"]["average_cost"], 360.0)
        self.assertEqual(payload["account"]["net_assets_usd"], 10000.0)
        self.assertEqual(payload["unconfirmed_legacy_holdings"], [])

    def test_legacy_monitoring_payload_has_no_symbol_specific_stops(self) -> None:
        payload = get_monitoring_payload()
        self.assertEqual(payload["urgent_count"], 0)
        self.assertEqual(payload["rules"][0]["status"], "deprecated")
        self.assertFalse(any(rule.get("symbol") for rule in payload["rules"]))

    def test_legacy_monitoring_payload_does_not_publish_static_guidance(self) -> None:
        self.assertEqual(get_monitoring_payload()["action_guidance"], [])

    def test_finnhub_hk_symbol_normalization(self) -> None:
        self.assertEqual(normalize_finnhub_symbol("00700.HK"), "700.HK")
        self.assertEqual(normalize_finnhub_symbol("AAPL"), "AAPL")

    def test_portfolio_payload_prefers_live_quote_when_available(self) -> None:
        def fake_provider(symbols: list[str]) -> dict[str, dict[str, object]]:
            self.assertEqual(set(symbols), {"AAPL", "MSFT", "SPY"})
            return {
                "AAPL": {
                    "status": "live",
                    "provider": "test",
                    "provider_symbol": "AAPL",
                    "price": 210.0,
                    "change_percent": 1.5,
                }
            }

        payload = get_portfolio_payload(include_live_quotes=True, quote_provider=fake_provider)
        by_symbol = {holding["symbol"]: holding for holding in payload["holdings"]}

        self.assertEqual(payload["live_quote_summary"]["live"], 1)
        self.assertEqual(payload["price_status"], "live_quotes_partial_snapshot_fallback")
        self.assertEqual(by_symbol["AAPL"]["display_price_source"], "live_quote")
        self.assertEqual(by_symbol["AAPL"]["live_market_value"], 1050.0)
        self.assertEqual(by_symbol["MSFT"]["display_price_source"], "snapshot_fallback")


if __name__ == "__main__":
    unittest.main()

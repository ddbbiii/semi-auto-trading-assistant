from __future__ import annotations

from datetime import datetime, timezone

from trading_assistant.domain import Cash, Holding, Instrument, OrderDraft, Quote


class SimulatedBroker:
    def __init__(self, cash_usd: float = 3000) -> None:
        self._cash = Cash(available_usd=cash_usd)
        self._holdings: dict[str, Holding] = {}
        self._quotes: dict[str, Quote] = {}
        self.submitted_order_ids: list[str] = []

    def set_quote(self, instrument: Instrument, bid: float, ask: float, last: float) -> None:
        self._quotes[instrument.symbol] = Quote(
            instrument=instrument,
            bid=bid,
            ask=ask,
            last=last,
            timestamp=datetime.now(timezone.utc),
        )

    def get_quote(self, instrument: Instrument) -> Quote:
        return self._quotes[instrument.symbol]

    def get_cash(self) -> Cash:
        return self._cash

    def get_holdings(self) -> tuple[Holding, ...]:
        return tuple(self._holdings.values())

    def submit_limit_order(self, draft: OrderDraft) -> str:
        self.submitted_order_ids.append(draft.order_intent_id)
        return draft.order_intent_id


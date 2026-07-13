from __future__ import annotations

from typing import Protocol

from trading_assistant.domain import Cash, Holding, Instrument, OrderDraft, Quote


class BrokerClient(Protocol):
    def get_quote(self, instrument: Instrument) -> Quote:
        raise NotImplementedError

    def get_cash(self) -> Cash:
        raise NotImplementedError

    def get_holdings(self) -> tuple[Holding, ...]:
        raise NotImplementedError

    def submit_limit_order(self, draft: OrderDraft) -> str:
        raise NotImplementedError


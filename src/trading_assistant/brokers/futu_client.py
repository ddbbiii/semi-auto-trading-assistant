from __future__ import annotations

from trading_assistant.domain import Cash, Holding, Instrument, OrderDraft, Quote


class FutuClient:
    """Read-first Futu adapter placeholder.

    Real trading must remain disabled until paper trading, audit logging, and
    product-specific controls have been validated.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111) -> None:
        try:
            import futu as ft  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install optional dependency with: pip install futu-api") from exc

        self._ft = ft
        self.host = host
        self.port = port

    def get_quote(self, instrument: Instrument) -> Quote:
        raise NotImplementedError("Futu quote adapter is not wired yet.")

    def get_cash(self) -> Cash:
        raise NotImplementedError("Futu account adapter is not wired yet.")

    def get_holdings(self) -> tuple[Holding, ...]:
        raise NotImplementedError("Futu holdings adapter is not wired yet.")

    def submit_limit_order(self, draft: OrderDraft) -> str:
        raise RuntimeError("Real Futu order submission is intentionally disabled.")


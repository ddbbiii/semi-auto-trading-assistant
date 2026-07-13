from __future__ import annotations

from trading_assistant.domain import Cash, Holding, Instrument, OrderDraft, Quote


class MoomooClient:
    """Read-first Moomoo adapter placeholder.

    Real trading must remain disabled until paper trading, audit logging, and
    product-specific controls have been validated.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111) -> None:
        try:
            import moomoo as mm  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install optional dependency with: pip install moomoo-api") from exc

        self._mm = mm
        self.host = host
        self.port = port

    def get_quote(self, instrument: Instrument) -> Quote:
        raise NotImplementedError("Moomoo quote adapter is not wired yet.")

    def get_cash(self) -> Cash:
        raise NotImplementedError("Moomoo account adapter is not wired yet.")

    def get_holdings(self) -> tuple[Holding, ...]:
        raise NotImplementedError("Moomoo holdings adapter is not wired yet.")

    def submit_limit_order(self, draft: OrderDraft) -> str:
        raise RuntimeError("Real Moomoo order submission is intentionally disabled.")


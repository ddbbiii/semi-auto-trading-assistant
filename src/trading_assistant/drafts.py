from __future__ import annotations

from .domain import Instrument, OrderDraft, Side


def create_limit_draft(
    instrument: Instrument,
    *,
    side: Side,
    quantity: float,
    limit_price: float,
    reason: str,
    failure_plan: str,
    validity_seconds: int = 60,
) -> OrderDraft:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if limit_price <= 0:
        raise ValueError("limit_price must be positive")
    return OrderDraft(
        instrument=instrument,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        reason=reason,
        failure_plan=failure_plan,
        validity_seconds=validity_seconds,
    )


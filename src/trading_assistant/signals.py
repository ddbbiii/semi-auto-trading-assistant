from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrendSignal:
    symbol: str
    above_medium_trend: bool
    relative_strength_rank: float
    volatility_rank: float
    rationale: str


def simple_trend_signal(
    symbol: str,
    last_price: float,
    moving_average: float,
    relative_strength_rank: float,
    volatility_rank: float,
) -> TrendSignal:
    above = last_price > moving_average
    rationale = "above trend" if above else "below trend"
    return TrendSignal(
        symbol=symbol,
        above_medium_trend=above,
        relative_strength_rank=relative_strength_rank,
        volatility_rank=volatility_rank,
        rationale=rationale,
    )


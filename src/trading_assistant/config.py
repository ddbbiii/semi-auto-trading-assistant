from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class RiskConfig:
    single_order_max_usd: float = 750
    single_symbol_max_usd: float = 1500
    theme_exposure_max_usd: float = 2000
    min_cash_after_order_usd: float = 500
    max_spread_bps: float = 80
    max_quote_age_seconds: int = 20
    max_price_move_bps_after_approval: float = 40
    max_daily_loss_usd: float = 150
    warrant_no_add_days_before_last_trade: int = 10


@dataclass(frozen=True)
class BrokerConfig:
    default: str = "simulated"
    host: str = "127.0.0.1"
    port: int = 11111


@dataclass(frozen=True)
class AppConfig:
    risk: RiskConfig
    broker: BrokerConfig


def load_config(path: str | Path = "configs/default.toml") -> AppConfig:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return AppConfig(
        risk=RiskConfig(**raw.get("risk", {})),
        broker=BrokerConfig(**raw.get("broker", {})),
    )


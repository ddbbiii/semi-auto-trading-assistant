from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DataQuality(BaseModel):
    provider: str
    observed_at: datetime | None = None
    freshness_seconds: int | None = None
    source_type: Literal["live", "snapshot", "fallback", "derived", "unavailable"]
    actionable: bool
    usage: Literal["execution", "monitoring", "reference", "unavailable"] = "unavailable"
    market_status: Literal["open", "closed", "unknown"] = "unknown"
    execution_ready: bool = False
    issues: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    kind: Literal["price", "position", "risk_rule", "filing", "news", "system"]
    title: str
    detail: str
    source_url: str | None = None
    observed_at: datetime | None = None


class OrderDraft(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    limit_price_low: float
    limit_price_high: float
    valid_until: datetime
    executable: bool = False


class Decision(BaseModel):
    id: str
    symbol: str
    name: str = ""
    title: str
    summary: str
    action: Literal["verify", "hold", "reduce", "exit", "add", "watch"]
    priority: Literal["urgent", "high", "normal", "opportunity"]
    current_weight_percent: float | None = None
    target_weight_percent: float | None = None
    quantity_delta: float | None = None
    trigger: str
    invalid_if: str
    current_limit: str = ""
    policy_response: Literal["review", "stop_adding", "reduce", "exit"] = "review"
    event_classification: Literal["value_event", "sentiment_liquidity", "mixed", "unexplained", "not_applicable"] = "not_applicable"
    information_grade: Literal["A", "B", "C", "unrated"] = "unrated"
    research_confidence: Literal["high", "medium", "low", "unrated"] = "unrated"
    investment_certainty: Literal["high", "medium", "low", "unrated"] = "unrated"
    confidence: Literal["high", "medium", "low"]
    data_quality: DataQuality
    evidence: list[Evidence]
    order_draft: OrderDraft | None = None
    generated_at: datetime
    expires_at: datetime
    status: Literal["new", "snoozed", "executed", "rejected", "expired"] = "new"


class DecisionFeedbackRequest(BaseModel):
    action: Literal["executed", "snoozed", "rejected"]
    executed_quantity: float | None = None
    executed_price: float | None = None
    note: str | None = Field(default=None, max_length=1000)


class AnalysisSettingsUpdate(BaseModel):
    interval_minutes: int = Field(default=120, ge=30, le=1440)
    analyze_us_premarket: bool = False
    analyze_regular_session: bool = True
    analyze_us_afterhours: bool = False


class HoldingRiskProfileInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    stop_price: float | None = Field(default=None, gt=0)
    target_weight_percent: float | None = Field(default=None, ge=0, le=100)
    thesis_invalidation: str = Field(default="", max_length=1000)
    thesis_summary: str = Field(default="", max_length=2000)
    information_grade: Literal["A", "B", "C", "unrated"] = "unrated"
    research_confidence: Literal["high", "medium", "low", "unrated"] = "unrated"
    investment_certainty: Literal["high", "medium", "low", "unrated"] = "unrated"
    strongest_bear_case: str = Field(default="", max_length=2000)
    buy_add_conditions: str = Field(default="", max_length=2000)
    reduce_conditions: str = Field(default="", max_length=2000)
    exit_invalidation_conditions: str = Field(default="", max_length=2000)
    bear_scenario: str = Field(default="", max_length=2000)
    base_scenario: str = Field(default="", max_length=2000)
    bull_scenario: str = Field(default="", max_length=2000)
    position_intent: Literal["long_term", "tactical", "derivative"] = "long_term"
    price_response: Literal["review", "stop_adding", "reduce", "exit"] = "review"
    expiry_date: date | None = None

    @model_validator(mode="after")
    def require_rule(self) -> HoldingRiskProfileInput:
        text_fields = (
            self.thesis_invalidation,
            self.thesis_summary,
            self.strongest_bear_case,
            self.buy_add_conditions,
            self.reduce_conditions,
            self.exit_invalidation_conditions,
            self.bear_scenario,
            self.base_scenario,
            self.bull_scenario,
        )
        if not any((self.stop_price, self.target_weight_percent is not None, self.expiry_date, *(value.strip() for value in text_fields))):
            raise ValueError("每组用户规则至少需要填写一项。")
        return self


class RiskConfigurationUpdate(BaseModel):
    max_single_position_percent: float = Field(default=25, ge=1, le=100)
    daily_move_alert_percent: float = Field(default=8, ge=1, le=100)
    warrant_expiry_warning_days: int = Field(default=30, ge=1, le=365)
    target_weight_tolerance_percent: float = Field(default=2, ge=0.1, le=25)
    profiles: list[HoldingRiskProfileInput] = Field(default_factory=list, max_length=500)


class HoldingInput(BaseModel):
    symbol: str
    name: str = ""
    market: Literal["US", "HK", "CN"]
    security_type: str = "stock"
    quantity: float
    available_quantity: float | None = None
    currency: Literal["USD", "HKD", "CNY"]
    market_value: float
    price: float
    average_cost: float
    theme: str = ""
    holding_pnl: float | None = None
    holding_pnl_percent: float | None = None


class SnapshotImportRequest(BaseModel):
    import_id: str | None = None
    source: str = "manual_confirmed"
    as_of: datetime
    account: dict[str, Any] = Field(default_factory=dict)
    holdings: list[HoldingInput]
    pending_order_count: int = 0


class ImportPreview(BaseModel):
    import_id: str
    file_name: str
    parser: str
    account: dict[str, Any]
    holdings: list[HoldingInput]
    warnings: list[str]
    requires_confirmation: bool = True

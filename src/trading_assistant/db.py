from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PortfolioSnapshotRecord(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    source: Mapped[str] = mapped_column(String(100))
    account_json: Mapped[str] = mapped_column(Text)
    pending_order_count: Mapped[int] = mapped_column(Integer, default=0)
    holdings: Mapped[list[HoldingRecord]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class HoldingRecord(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[PortfolioSnapshotRecord] = relationship(back_populates="holdings")


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


class DecisionFeedbackRecord(Base):
    __tablename__ = "decision_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    action: Mapped[str] = mapped_column(String(24))
    executed_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SyncRunRecord(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuoteRecord(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


class FxRateRecord(Base):
    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency: Mapped[str] = mapped_column(String(8), index=True)
    rate_to_cny: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(80))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EvidenceRecord(Base):
    __tablename__ = "evidence_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


class ImportRunRecord(Base):
    __tablename__ = "import_runs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    parser: Mapped[str] = mapped_column(String(32))
    file_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), index=True)
    holding_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OpportunityWatchlistRecord(Base):
    __tablename__ = "opportunity_watchlist"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SecurityThemeRecord(Base):
    __tablename__ = "security_themes"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    theme: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AnalysisSettingsRecord(Base):
    __tablename__ = "analysis_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    analyze_us_premarket: Mapped[bool] = mapped_column(Boolean, default=False)
    analyze_regular_session: Mapped[bool] = mapped_column(Boolean, default=True)
    analyze_us_afterhours: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RiskSettingsRecord(Base):
    __tablename__ = "risk_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_single_position_percent: Mapped[float] = mapped_column(Float, default=25.0)
    daily_move_alert_percent: Mapped[float] = mapped_column(Float, default=8.0)
    warrant_expiry_warning_days: Mapped[int] = mapped_column(Integer, default=30)
    target_weight_tolerance_percent: Mapped[float] = mapped_column(Float, default=2.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HoldingRiskProfileRecord(Base):
    __tablename__ = "holding_risk_profiles"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_weight_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    thesis_invalidation: Mapped[str | None] = mapped_column(Text, nullable=True)
    thesis_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    information_grade: Mapped[str] = mapped_column(String(16), default="unrated")
    research_confidence: Mapped[str] = mapped_column(String(16), default="unrated")
    investment_certainty: Mapped[str] = mapped_column(String(16), default="unrated")
    strongest_bear_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    buy_add_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    reduce_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_invalidation_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    bear_scenario: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_scenario: Mapped[str | None] = mapped_column(Text, nullable=True)
    bull_scenario: Mapped[str | None] = mapped_column(Text, nullable=True)
    position_intent: Mapped[str] = mapped_column(String(24), default="long_term")
    price_response: Mapped[str] = mapped_column(String(24), default="review")
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    activation_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="user_confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def default_database_url() -> str:
    data_dir = Path(os.getenv("TRADING_ASSISTANT_DATA_DIR", "data/runtime")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'trading-assistant.sqlite3').as_posix()}"


class Store:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("TRADING_ASSISTANT_DATABASE_URL") or default_database_url()
        self.engine = create_engine(
            self.database_url,
            connect_args={"check_same_thread": False} if self.database_url.startswith("sqlite") else {},
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    def has_snapshot(self) -> bool:
        with self.session() as session:
            return session.scalar(select(PortfolioSnapshotRecord.id).limit(1)) is not None

    def save_snapshot(self, payload: dict[str, Any]) -> int:
        as_of = _parse_datetime(payload["as_of"])
        with self.session() as session:
            record = PortfolioSnapshotRecord(
                as_of=as_of,
                source=str(payload.get("source", "manual_confirmed")),
                account_json=json.dumps(payload.get("account", {}), ensure_ascii=False),
                pending_order_count=int(payload.get("pending_order_count", len(payload.get("pending_orders", [])))),
            )
            for holding in payload.get("holdings", []):
                record.holdings.append(
                    HoldingRecord(symbol=str(holding["symbol"]).upper(), payload_json=json.dumps(holding, ensure_ascii=False))
                )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.id

    def latest_snapshot(self) -> dict[str, Any] | None:
        with self.session() as session:
            record = session.scalars(
                select(PortfolioSnapshotRecord).order_by(PortfolioSnapshotRecord.as_of.desc()).limit(1)
            ).first()
            if record is None:
                return None
            holdings = [json.loads(item.payload_json) for item in record.holdings]
            return {
                "id": record.id,
                "as_of": _iso(record.as_of),
                "source": record.source,
                "account": json.loads(record.account_json),
                "pending_order_count": record.pending_order_count,
                "pending_orders": [],
                "holdings": holdings,
                "holding_count": len(holdings),
            }

    def replace_decisions(self, decisions: list[dict[str, Any]]) -> None:
        with self.session() as session:
            active = session.scalars(select(DecisionRecord).where(DecisionRecord.status.in_(("new", "snoozed")))).all()
            for record in active:
                record.status = "expired"
                payload = json.loads(record.payload_json)
                payload["status"] = "expired"
                record.payload_json = json.dumps(payload, ensure_ascii=False)
            for item in decisions:
                session.merge(
                    DecisionRecord(
                        id=item["id"],
                        symbol=item["symbol"],
                        priority=item["priority"],
                        status=item["status"],
                        generated_at=_parse_datetime(item["generated_at"]),
                        expires_at=_parse_datetime(item["expires_at"]),
                        payload_json=json.dumps(item, ensure_ascii=False),
                    )
                )
            session.commit()

    def active_decisions(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        with self.session() as session:
            records = session.scalars(
                select(DecisionRecord)
                .where(DecisionRecord.status.in_(("new", "snoozed")), DecisionRecord.expires_at > now)
                .order_by(DecisionRecord.generated_at.desc())
            ).all()
            return [json.loads(record.payload_json) | {"status": record.status} for record in records]

    def save_feedback(
        self,
        decision_id: str,
        *,
        action: str,
        executed_quantity: float | None,
        executed_price: float | None,
        note: str | None,
    ) -> dict[str, Any] | None:
        with self.session() as session:
            decision = session.get(DecisionRecord, decision_id)
            if decision is None:
                return None
            decision.status = action
            payload = json.loads(decision.payload_json)
            payload["status"] = action
            decision.payload_json = json.dumps(payload, ensure_ascii=False)
            session.add(
                DecisionFeedbackRecord(
                    decision_id=decision_id,
                    action=action,
                    executed_quantity=executed_quantity,
                    executed_price=executed_price,
                    note=note,
                )
            )
            session.commit()
            return payload

    def record_quotes(self, quotes: dict[str, dict[str, Any]]) -> None:
        with self.session() as session:
            for symbol, quote in quotes.items():
                observed = quote.get("observed_at") or quote.get("fetched_at")
                if not observed:
                    continue
                session.add(
                    QuoteRecord(
                        symbol=symbol,
                        provider=str(quote.get("provider", "unknown")),
                        observed_at=_parse_datetime(observed),
                        payload_json=json.dumps(quote, ensure_ascii=False),
                    )
                )
            session.commit()

    def record_fx_rates(self, rates: dict[str, float], *, provider: str, observed_at: datetime) -> None:
        with self.session() as session:
            session.add_all(
                FxRateRecord(currency=currency, rate_to_cny=rate, provider=provider, observed_at=observed_at)
                for currency, rate in rates.items()
            )
            session.commit()

    def record_import_preview(self, payload: dict[str, Any]) -> None:
        with self.session() as session:
            session.merge(
                ImportRunRecord(
                    id=payload["import_id"],
                    parser=payload["parser"],
                    file_name=payload["file_name"],
                    status="previewed",
                    holding_count=len(payload.get("holdings", [])),
                    warnings_json=json.dumps(payload.get("warnings", []), ensure_ascii=False),
                )
            )
            session.commit()

    def commit_import(self, import_id: str | None) -> None:
        if not import_id:
            return
        with self.session() as session:
            record = session.get(ImportRunRecord, import_id)
            if record:
                record.status = "committed"
                record.committed_at = datetime.now(timezone.utc)
                session.commit()

    def replace_opportunity_watchlist(self, items: list[dict[str, Any]], *, source: str) -> None:
        now = datetime.now(timezone.utc)
        with self.session() as session:
            session.execute(delete(OpportunityWatchlistRecord))
            session.add_all(
                OpportunityWatchlistRecord(
                    symbol=str(item["symbol"]).upper(),
                    position=position,
                    payload_json=json.dumps(item, ensure_ascii=False),
                    source=source,
                    updated_at=now,
                )
                for position, item in enumerate(items)
            )
            session.commit()

    def opportunity_watchlist(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with self.session() as session:
            records = list(
                session.scalars(select(OpportunityWatchlistRecord).order_by(OpportunityWatchlistRecord.position))
            )
        if not records:
            return [], {"source": "built_in_default", "updated_at": None}
        return (
            [json.loads(record.payload_json) for record in records],
            {"source": records[0].source, "updated_at": records[0].updated_at.isoformat()},
        )

    def security_themes(self) -> dict[str, dict[str, Any]]:
        with self.session() as session:
            records = list(session.scalars(select(SecurityThemeRecord)))
        return {
            record.symbol: {
                "theme": record.theme,
                "source": record.source,
                "updated_at": _iso(record.updated_at),
            }
            for record in records
        }

    def upsert_security_themes(self, themes: dict[str, str], *, source: str) -> None:
        if not themes:
            return
        now = datetime.now(timezone.utc)
        with self.session() as session:
            for symbol, theme in themes.items():
                session.merge(
                    SecurityThemeRecord(
                        symbol=symbol.upper(),
                        theme=theme,
                        source=source,
                        updated_at=now,
                    )
                )
            session.commit()

    def analysis_settings(self) -> dict[str, Any]:
        with self.session() as session:
            record = session.get(AnalysisSettingsRecord, 1)
            if record is None:
                record = AnalysisSettingsRecord(id=1)
                session.add(record)
                session.commit()
                session.refresh(record)
            return {
                "interval_minutes": record.interval_minutes,
                "analyze_us_premarket": record.analyze_us_premarket,
                "analyze_regular_session": record.analyze_regular_session,
                "analyze_us_afterhours": record.analyze_us_afterhours,
                "updated_at": _iso(record.updated_at),
            }

    def update_analysis_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.session() as session:
            record = session.get(AnalysisSettingsRecord, 1) or AnalysisSettingsRecord(id=1)
            record.interval_minutes = int(payload["interval_minutes"])
            record.analyze_us_premarket = bool(payload["analyze_us_premarket"])
            record.analyze_regular_session = bool(payload["analyze_regular_session"])
            record.analyze_us_afterhours = bool(payload["analyze_us_afterhours"])
            record.updated_at = now
            session.add(record)
            session.commit()
        return self.analysis_settings()

    def risk_settings(self) -> dict[str, Any]:
        with self.session() as session:
            record = session.get(RiskSettingsRecord, 1)
            if record is None:
                record = RiskSettingsRecord(id=1)
                session.add(record)
                session.commit()
                session.refresh(record)
            return {
                "max_single_position_percent": record.max_single_position_percent,
                "daily_move_alert_percent": record.daily_move_alert_percent,
                "warrant_expiry_warning_days": record.warrant_expiry_warning_days,
                "target_weight_tolerance_percent": record.target_weight_tolerance_percent,
                "updated_at": _iso(record.updated_at),
            }

    def update_risk_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.session() as session:
            record = session.get(RiskSettingsRecord, 1) or RiskSettingsRecord(id=1)
            record.max_single_position_percent = float(payload["max_single_position_percent"])
            record.daily_move_alert_percent = float(payload["daily_move_alert_percent"])
            record.warrant_expiry_warning_days = int(payload["warrant_expiry_warning_days"])
            record.target_weight_tolerance_percent = float(payload["target_weight_tolerance_percent"])
            record.updated_at = now
            session.add(record)
            session.commit()
        return self.risk_settings()

    def risk_profiles(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        with self.session() as session:
            statement = select(HoldingRiskProfileRecord).order_by(HoldingRiskProfileRecord.symbol)
            if active_only:
                statement = statement.where(HoldingRiskProfileRecord.status == "active")
            records = list(session.scalars(statement))
        return [
            {
                "symbol": record.symbol,
                "stop_price": record.stop_price,
                "target_weight_percent": record.target_weight_percent,
                "thesis_invalidation": record.thesis_invalidation or "",
                "thesis_summary": record.thesis_summary or "",
                "information_grade": record.information_grade or "unrated",
                "research_confidence": record.research_confidence or "unrated",
                "investment_certainty": record.investment_certainty or "unrated",
                "strongest_bear_case": record.strongest_bear_case or "",
                "buy_add_conditions": record.buy_add_conditions or "",
                "reduce_conditions": record.reduce_conditions or "",
                "exit_invalidation_conditions": record.exit_invalidation_conditions or "",
                "bear_scenario": record.bear_scenario or "",
                "base_scenario": record.base_scenario or "",
                "bull_scenario": record.bull_scenario or "",
                "position_intent": record.position_intent or "long_term",
                "price_response": record.price_response or "review",
                "expiry_date": record.expiry_date.isoformat() if record.expiry_date else None,
                "status": record.status,
                "source": record.source,
                "activation_snapshot_id": record.activation_snapshot_id,
                "updated_at": _iso(record.updated_at),
                "deactivated_at": _iso(record.deactivated_at) if record.deactivated_at else None,
            }
            for record in records
        ]

    def replace_user_risk_profiles(self, profiles: list[dict[str, Any]], snapshot: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        snapshot_id = int(snapshot["id"])
        held_symbols = {
            str(item["symbol"]).upper()
            for item in snapshot.get("holdings", [])
            if float(item.get("quantity") or 0) > 0
        }
        incoming = {str(item["symbol"]).upper(): item for item in profiles}
        with self.session() as session:
            existing = {
                record.symbol: record
                for record in session.scalars(
                    select(HoldingRiskProfileRecord).where(HoldingRiskProfileRecord.source == "user_confirmed")
                )
            }
            for symbol, record in existing.items():
                if symbol not in incoming and record.status == "active":
                    record.status = "disabled_by_user"
                    record.deactivated_at = now
                    record.updated_at = now
            for symbol, item in incoming.items():
                record = existing.get(symbol) or HoldingRiskProfileRecord(symbol=symbol, source="user_confirmed")
                record.stop_price = item.get("stop_price")
                record.target_weight_percent = item.get("target_weight_percent")
                record.thesis_invalidation = str(item.get("thesis_invalidation") or "").strip() or None
                record.thesis_summary = str(item.get("thesis_summary") or "").strip() or None
                record.information_grade = str(item.get("information_grade") or "unrated")
                record.research_confidence = str(item.get("research_confidence") or "unrated")
                record.investment_certainty = str(item.get("investment_certainty") or "unrated")
                record.strongest_bear_case = str(item.get("strongest_bear_case") or "").strip() or None
                record.buy_add_conditions = str(item.get("buy_add_conditions") or "").strip() or None
                record.reduce_conditions = str(item.get("reduce_conditions") or "").strip() or None
                record.exit_invalidation_conditions = str(item.get("exit_invalidation_conditions") or "").strip() or None
                record.bear_scenario = str(item.get("bear_scenario") or "").strip() or None
                record.base_scenario = str(item.get("base_scenario") or "").strip() or None
                record.bull_scenario = str(item.get("bull_scenario") or "").strip() or None
                record.position_intent = str(item.get("position_intent") or "long_term")
                record.price_response = str(item.get("price_response") or "review")
                record.expiry_date = item.get("expiry_date")
                record.status = "active" if symbol in held_symbols else "inactive_cleared"
                record.activation_snapshot_id = snapshot_id if symbol in held_symbols else None
                record.deactivated_at = None if symbol in held_symbols else now
                record.updated_at = now
                session.add(record)
            session.commit()

    def reconcile_risk_profiles(self, snapshot: dict[str, Any]) -> None:
        held_symbols = {
            str(item["symbol"]).upper()
            for item in snapshot.get("holdings", [])
            if float(item.get("quantity") or 0) > 0
        }
        now = datetime.now(timezone.utc)
        with self.session() as session:
            records = list(
                session.scalars(select(HoldingRiskProfileRecord).where(HoldingRiskProfileRecord.status == "active"))
            )
            changed = False
            for record in records:
                if record.symbol not in held_symbols:
                    record.status = "inactive_cleared"
                    record.deactivated_at = now
                    record.updated_at = now
                    changed = True
            if changed:
                session.commit()

    def latest_completed_sync(self, source: str) -> datetime | None:
        with self.session() as session:
            record = session.scalars(
                select(SyncRunRecord)
                .where(SyncRunRecord.source == source, SyncRunRecord.status == "completed")
                .order_by(SyncRunRecord.completed_at.desc())
                .limit(1)
            ).first()
            if record is None or record.completed_at is None:
                return None
            completed_at = record.completed_at
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=timezone.utc)
            return completed_at

    def start_sync(self, source: str) -> int:
        with self.session() as session:
            record = SyncRunRecord(source=source, status="running")
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.id

    def finish_sync(self, run_id: int, *, status: str, detail: str = "") -> None:
        with self.session() as session:
            record = session.get(SyncRunRecord, run_id)
            if record:
                record.status = status
                record.detail = detail
                record.completed_at = datetime.now(timezone.utc)
                session.commit()


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()

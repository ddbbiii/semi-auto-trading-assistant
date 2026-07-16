from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from threading import Lock
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .analysis_schedule import schedule_status
from .audit import AuditLog
from .brokers.simulated import SimulatedBroker
from .config import load_config
from .db import Store
from .decision_engine import DEFAULT_WATCHLIST, build_decisions, build_opportunities
from .domain import Cash, Instrument, Market, PortfolioSnapshot, SecurityType, Side
from .drafts import create_limit_draft
from .fx import get_rates_to_cny
from .imports import preview_import_batch, snapshot_payload
from .investment_policy import investment_policy_payload
from .llm import analyze_refresh_with_report, status as llm_status, test_connection as test_llm_connection
from .notifications import EmailAlertConfig, maybe_send_decision_alert_email
from .portfolio_state import CURRENT_PORTFOLIO, get_monitoring_payload, get_portfolio_payload
from .providers import futu_status, get_quotes
from .risk import RiskEngine
from .schemas import AnalysisSettingsUpdate, DecisionFeedbackRequest, ImportPreview, RiskConfigurationUpdate, SnapshotImportRequest
from .themes import ensure_security_themes, resolve_security_themes
from .vision import preview_images_with_vision, vision_import_enabled


_decision_refresh_lock = Lock()


@dataclass(frozen=True)
class DecisionRefreshResult:
    decisions: list[dict[str, Any]]
    checked_holdings: int
    active_user_rules: int
    model_status: str
    model_summary: str | None
    analysis_report: dict[str, Any] | None
    market_data_status: str
    market_data_live: int
    market_data_total: int
    market_data_fallback: int
    completed_at: datetime

    def payload(self) -> dict[str, Any]:
        return {
            "status": "refreshed",
            "decisions": self.decisions,
            "summary": {
                "checked_holdings": self.checked_holdings,
                "generic_rules": 3,
                "active_user_rules": self.active_user_rules,
                "decision_count": len(self.decisions),
                "model_status": self.model_status,
                "model_summary": self.model_summary,
                "backend_status": "success",
                "market_data_status": self.market_data_status,
                "market_data_live": self.market_data_live,
                "market_data_total": self.market_data_total,
                "market_data_fallback": self.market_data_fallback,
                "completed_at": self.completed_at.isoformat(),
            },
            "analysis_report": self.analysis_report,
        }


def build_health_payload() -> dict[str, Any]:
    config = load_config()
    return {
        "status": "ok",
        "service": "semi-auto-trading-assistant-api",
        "broker": config.broker.default,
        "single_order_max_usd": config.risk.single_order_max_usd,
    }


def build_demo_draft_payload() -> dict[str, Any]:
    config = load_config()
    broker = SimulatedBroker(cash_usd=3000)
    demo_instrument = Instrument(
        symbol="AAPL",
        market=Market.US,
        security_type=SecurityType.STOCK,
        theme="consumer_technology",
        name="Apple Inc.",
    )
    broker.set_quote(demo_instrument, bid=199.5, ask=200.0, last=199.8)
    draft = create_limit_draft(
        demo_instrument,
        side=Side.BUY,
        quantity=1,
        limit_price=199.0,
        reason="Synthetic demo only: starter position draft.",
        failure_plan="If the quote leaves the validity band, regenerate the draft.",
    )
    portfolio = PortfolioSnapshot(cash=Cash(available_usd=3000), holdings=())
    risk = RiskEngine(config.risk).check(draft, broker.get_quote(demo_instrument), portfolio)
    AuditLog("data/runtime/audit.sqlite3").append(
        "demo_draft_created", {"draft": draft, "risk": risk}, order_intent_id=draft.order_intent_id
    )
    return {
        "draft": {
            "order_intent_id": draft.order_intent_id,
            "symbol": draft.instrument.symbol,
            "side": draft.side.value,
            "quantity": draft.quantity,
            "limit_price": draft.limit_price,
            "notional": draft.notional,
            "reason": draft.reason,
            "validity_seconds": draft.validity_seconds,
        },
        "risk": {"allowed": risk.allowed, "reasons": list(risk.reasons)},
    }


def create_app(store: Store | None = None, *, schedule: bool | None = None) -> FastAPI:
    application_store = store or Store()
    scheduler: BackgroundScheduler | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal scheduler
        application_store.create_schema()
        if not application_store.has_snapshot():
            application_store.save_snapshot(CURRENT_PORTFOLIO)
        current_snapshot = application_store.latest_snapshot()
        if current_snapshot:
            ensure_security_themes(application_store, current_snapshot.get("holdings", []))
            application_store.reconcile_risk_profiles(current_snapshot)
        app.state.store = application_store
        refresh_decisions(application_store, enrich=False, source="startup_refresh")
        schedule_enabled = schedule if schedule is not None else os.getenv("TRADING_ASSISTANT_SCHEDULER_ENABLED", "1") == "1"
        if schedule_enabled:
            scheduler = _start_scheduler(application_store)
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        application_store.close()

    app = FastAPI(title="Personal Investment Decision Desk", version="1.0.0", lifespan=lifespan)
    origins = [
        value.strip()
        for value in os.getenv(
            "TRADING_ASSISTANT_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if value.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    def current_store(request: Request) -> Store:
        return request.app.state.store

    @app.get("/")
    def root() -> dict[str, Any]:
        return {"status": "ok", "service": "personal-investment-decision-desk", "api": "/api/v1"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return build_health_payload()

    @app.get("/api/v1/dashboard")
    def dashboard(db: Store = Depends(current_store)) -> dict[str, Any]:
        snapshot = _snapshot_with_quotes(db)
        decisions = db.active_decisions()
        decision_symbols = {item["symbol"] for item in decisions}
        analysis_settings = db.analysis_settings()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": _snapshot_meta(snapshot),
            "account": snapshot.get("account", {}),
            "summary": _portfolio_summary(snapshot, db),
            "llm": llm_status(),
            "decisions": decisions[:3],
            "analysis_report": db.latest_analysis_report(),
            "stable_holdings": [
                item
                for item in snapshot["holdings"]
                if item["symbol"] not in decision_symbols and float(item.get("quantity") or 0) > 0
            ],
            "next_runs": [
                "每 15 分钟轻量风险监控",
                f"启用时段内每 {analysis_settings['interval_minutes']} 分钟完整分析",
            ],
        }

    @app.get("/api/v1/holdings")
    def holdings(db: Store = Depends(current_store)) -> dict[str, Any]:
        snapshot = _snapshot_with_quotes(db)
        return {
            "snapshot": _snapshot_meta(snapshot),
            "account": snapshot.get("account", {}),
            "summary": _portfolio_summary(snapshot, db),
            "holdings": snapshot["holdings"],
        }

    @app.get("/api/v1/opportunities")
    def opportunities(db: Store = Depends(current_store)) -> dict[str, Any]:
        watchlist, metadata = db.opportunity_watchlist()
        active_watchlist = watchlist or list(DEFAULT_WATCHLIST)
        symbols = [item["symbol"] for item in active_watchlist]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "watchlist": metadata,
            "items": build_opportunities(get_quotes(symbols), watchlist=active_watchlist),
        }

    @app.post("/api/v1/import/preview", response_model=ImportPreview)
    async def import_preview(
        files: list[UploadFile] | None = File(default=None),
        file: UploadFile | None = File(default=None),
        db: Store = Depends(current_store),
    ) -> ImportPreview:
        try:
            uploads = list(files or [])
            if file is not None:
                uploads.insert(0, file)
            if not uploads:
                raise ValueError("至少需要一个文件。")
            payloads = [(upload.filename or "upload", upload.content_type, await upload.read()) for upload in uploads]
            if vision_import_enabled() and all(
                (content_type or "").startswith("image/")
                or file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                for file_name, content_type, _ in payloads
            ):
                try:
                    preview = preview_images_with_vision(payloads)
                except Exception:
                    preview = preview_import_batch(payloads)
                    preview.warnings.insert(0, "视觉模型识别暂时不可用，已自动回退到服务器本地 OCR，请加强人工核对。")
            else:
                preview = preview_import_batch(payloads)
            snapshot = db.latest_snapshot()
            if snapshot:
                known_holdings = {str(item.get("symbol", "")).upper(): item for item in snapshot.get("holdings", [])}
                preview.holdings = [
                    holding.model_copy(
                        update={
                            "name": known.get("name") or holding.name,
                            "security_type": known.get("security_type") or holding.security_type,
                            "theme": known.get("theme") or holding.theme,
                        }
                    )
                    if (known := known_holdings.get(holding.symbol.upper()))
                    else holding
                    for holding in preview.holdings
                ]
            preview_themes = resolve_security_themes(
                [holding.model_dump(mode="json") for holding in preview.holdings],
                db.security_themes(),
            )
            preview.holdings = [
                holding.model_copy(update={"theme": preview_themes.get(holding.symbol.upper(), "未分类")})
                for holding in preview.holdings
            ]
            db.record_import_preview(preview.model_dump(mode="json"))
            return preview
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"文件解析失败：{exc}") from exc

    @app.post("/api/v1/import/commit")
    def import_commit(payload: SnapshotImportRequest, db: Store = Depends(current_store)) -> dict[str, Any]:
        if not payload.holdings:
            raise HTTPException(status_code=400, detail="至少需要一条确认后的持仓。")
        confirmed_snapshot = snapshot_payload(payload)
        snapshot_id = db.save_snapshot(confirmed_snapshot)
        latest_snapshot = db.latest_snapshot()
        if latest_snapshot:
            db.reconcile_risk_profiles(latest_snapshot)
        ensure_security_themes(db, confirmed_snapshot.get("holdings", []))
        db.commit_import(payload.import_id)
        result = refresh_decisions(db)
        return {"status": "committed", "snapshot_id": snapshot_id, "decision_count": len(result.decisions)}

    @app.post("/api/v1/decisions/refresh")
    def decisions_refresh(db: Store = Depends(current_store)) -> dict[str, Any]:
        return refresh_decisions(db).payload()

    @app.post("/api/v1/themes/refresh")
    def themes_refresh(db: Store = Depends(current_store)) -> dict[str, Any]:
        snapshot = db.latest_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="还没有持仓快照。")
        themes = ensure_security_themes(db, snapshot.get("holdings", []))
        return {
            "status": "refreshed",
            "classified": sum(1 for theme in themes.values() if theme != "未分类"),
            "unclassified": sum(1 for theme in themes.values() if theme == "未分类"),
        }

    @app.post("/api/v1/decisions/{decision_id}/feedback")
    def decision_feedback(
        decision_id: str,
        payload: DecisionFeedbackRequest,
        db: Store = Depends(current_store),
    ) -> dict[str, Any]:
        result = db.save_feedback(
            decision_id,
            action=payload.action,
            executed_quantity=payload.executed_quantity,
            executed_price=payload.executed_price,
            note=payload.note,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="决策不存在。")
        return {"status": "saved", "decision": result}

    @app.get("/api/v1/system/status")
    def system_status(db: Store = Depends(current_store)) -> dict[str, Any]:
        snapshot = db.latest_snapshot()
        email = EmailAlertConfig.from_env()
        return {
            "database": {"status": "ok", "url": _safe_database_label(db.database_url)},
            "portfolio": _snapshot_meta(snapshot) if snapshot else {"status": "missing"},
            "futu": futu_status(),
            "llm": llm_status(),
            "email": {"status": "configured" if email.enabled and not email.missing_fields else "not_configured"},
            "news": {"status": "degraded", "detail": "官方公告聚合器待配置。"},
            "analysis_schedule": _analysis_settings_payload(db),
        }

    @app.post("/api/v1/system/test-llm")
    def system_test_llm() -> dict[str, Any]:
        """Test the configured model connection without changing portfolio or decisions."""
        return test_llm_connection()

    @app.get("/api/v1/settings/analysis")
    def get_analysis_settings(db: Store = Depends(current_store)) -> dict[str, Any]:
        return _analysis_settings_payload(db)

    @app.put("/api/v1/settings/analysis")
    def update_analysis_settings(
        payload: AnalysisSettingsUpdate,
        db: Store = Depends(current_store),
    ) -> dict[str, Any]:
        db.update_analysis_settings(payload.model_dump())
        return _analysis_settings_payload(db)

    @app.get("/api/v1/settings/risk")
    def get_risk_configuration(db: Store = Depends(current_store)) -> dict[str, Any]:
        return _risk_configuration_payload(db)

    @app.get("/api/v1/settings/investment-policy")
    def get_investment_policy() -> dict[str, Any]:
        return investment_policy_payload()

    @app.put("/api/v1/settings/risk")
    def update_risk_configuration(
        payload: RiskConfigurationUpdate,
        db: Store = Depends(current_store),
    ) -> dict[str, Any]:
        snapshot = db.latest_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="还没有持仓快照。")
        symbols = [profile.symbol.strip().upper() for profile in payload.profiles]
        if len(symbols) != len(set(symbols)):
            raise HTTPException(status_code=422, detail="同一标的只能保存一组用户规则。")
        db.update_risk_settings(payload.model_dump(exclude={"profiles"}))
        db.replace_user_risk_profiles(
            [profile.model_dump() | {"symbol": profile.symbol.strip().upper()} for profile in payload.profiles],
            snapshot,
        )
        refresh_decisions(db, enrich=False, source="risk_settings_update")
        return _risk_configuration_payload(db)

    @app.get("/portfolio")
    def legacy_portfolio(db: Store = Depends(current_store)) -> dict[str, Any]:
        return _snapshot_with_quotes(db)

    @app.get("/monitoring")
    def legacy_monitoring() -> dict[str, Any]:
        return get_monitoring_payload(include_live_quotes=True, quote_provider=get_quotes)

    @app.get("/demo-draft")
    def demo_draft() -> dict[str, Any]:
        return build_demo_draft_payload()

    return app


def refresh_decisions(
    store: Store,
    *,
    notify: bool = False,
    enrich: bool = True,
    source: str | None = None,
) -> DecisionRefreshResult:
    with _decision_refresh_lock:
        sync_source = source or ("scheduled_decision" if notify else "manual_decision")
        run_id = store.start_sync(sync_source)
        try:
            snapshot = _snapshot_with_quotes(store, force_quotes=True)
            quote_summary = snapshot.get("live_quote_summary") or {}
            market_data_status = {
                "ok": "success",
                "partial": "partial",
                "unavailable": "failed",
            }.get(str(quote_summary.get("status")), "failed")
            market_data_live = int(quote_summary.get("live") or 0)
            market_data_total = int(quote_summary.get("total") or 0)
            market_data_fallback = int(quote_summary.get("fallback_provider_count") or 0)
            store.reconcile_risk_profiles(snapshot)
            quotes = {item["symbol"]: item.get("live_quote", {}) for item in snapshot["holdings"]}
            profiles = store.risk_profiles(active_only=True)
            decisions = [
                item.model_dump(mode="json")
                for item in build_decisions(
                    snapshot,
                    quotes,
                    risk_settings=store.risk_settings(),
                    risk_profiles=profiles,
                )
            ]
            model_status = "skipped_lightweight"
            model_summary = None
            analysis_report = None
            if enrich:
                decisions, model_status, model_summary, analysis_report = analyze_refresh_with_report(
                    decisions,
                    _model_analysis_context(snapshot, profiles),
                )
                completed_at = datetime.now(timezone.utc)
                analysis_report = analysis_report | {
                    "generated_at": completed_at.isoformat(),
                    "source": sync_source,
                    "model_status": model_status,
                }
                store.save_analysis_report(analysis_report)
            else:
                completed_at = datetime.now(timezone.utc)
            store.replace_decisions(decisions)
            if notify:
                actionable = [
                    item
                    for item in decisions
                    if item["priority"] == "urgent" and item["data_quality"]["actionable"]
                ]
                if actionable:
                    maybe_send_decision_alert_email(actionable)
            checked = sum(1 for item in snapshot["holdings"] if float(item.get("quantity") or 0) > 0)
            detail = f"{len(decisions)} decisions; {checked} holdings; {len(profiles)} user rules; model={model_status}"
            store.finish_sync(run_id, status="completed", detail=detail)
            return DecisionRefreshResult(
                decisions=decisions,
                checked_holdings=checked,
                active_user_rules=len(profiles),
                model_status=model_status,
                model_summary=model_summary,
                analysis_report=analysis_report,
                market_data_status=market_data_status,
                market_data_live=market_data_live,
                market_data_total=market_data_total,
                market_data_fallback=market_data_fallback,
                completed_at=completed_at,
            )
        except Exception as exc:
            store.finish_sync(run_id, status="failed", detail=str(exc)[:1000])
            raise


def _snapshot_with_quotes(store: Store, *, force_quotes: bool = False) -> dict[str, Any]:
    snapshot = store.latest_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="还没有持仓快照。")
    themes = resolve_security_themes(snapshot["holdings"], store.security_themes())
    symbols = [item["symbol"] for item in snapshot["holdings"]]
    quote_map = get_quotes(symbols, force=force_quotes)
    store.record_quotes(quote_map)
    live_count = 0
    fallback_provider_count = 0
    for holding in snapshot["holdings"]:
        holding["theme"] = themes.get(str(holding["symbol"]).upper(), "未分类")
        quote = quote_map.get(holding["symbol"], {})
        holding["live_quote"] = quote
        if quote.get("status") == "live" and isinstance(quote.get("price"), (int, float)):
            live_count += 1
            if quote.get("fallback_from"):
                fallback_provider_count += 1
            holding["live_price"] = quote["price"]
            holding["live_market_value"] = round(float(quote["price"]) * float(holding["quantity"]), 4)
            holding["display_price_source"] = "live_quote"
        else:
            holding["live_price"] = None
            holding["live_market_value"] = None
            holding["display_price_source"] = "snapshot_fallback"
    snapshot["live_quote_summary"] = {
        "total": len(symbols),
        "live": live_count,
        "fallback": len(symbols) - live_count,
        "fallback_provider_count": fallback_provider_count,
        "status": "ok" if live_count == len(symbols) and fallback_provider_count == 0 else "partial" if live_count else "unavailable",
    }
    return snapshot


def _snapshot_meta(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "missing"}
    as_of = datetime.fromisoformat(str(snapshot["as_of"]).replace("Z", "+00:00"))
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - as_of).total_seconds()))
    return {
        "status": "confirmed",
        "as_of": as_of.isoformat(),
        "source": snapshot.get("source"),
        "age_seconds": age,
        "holding_count": len(snapshot.get("holdings", [])),
        "quote_summary": snapshot.get("live_quote_summary"),
    }


def _model_analysis_context(
    snapshot: dict[str, Any],
    profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a model-safe portfolio view without account values, costs, or quantities."""
    profile_symbols = {str(item.get("symbol") or "").upper() for item in profiles}
    holdings = []
    live_quote_count = 0
    for holding in snapshot.get("holdings", []):
        if float(holding.get("quantity") or 0) <= 0:
            continue
        symbol = str(holding.get("symbol") or "").upper()
        quote = holding.get("live_quote") or {}
        if quote.get("status") == "live" and isinstance(quote.get("price"), (int, float)):
            live_quote_count += 1
        holdings.append(
            {
                "symbol": symbol,
                "name": str(holding.get("name") or symbol),
                "market": str(holding.get("market") or ""),
                "security_type": str(holding.get("security_type") or "stock"),
                "theme": str(holding.get("theme") or "未分类"),
                "quote_status": str(quote.get("status") or "unavailable"),
                "price": quote.get("price"),
                "quote_provider": str(quote.get("provider") or "unknown"),
                "quote_observed_at": quote.get("observed_at") or quote.get("fetched_at"),
                "market_session": str(quote.get("market_session") or "unknown"),
                "price_session": str(quote.get("price_session") or "unknown"),
                "change_percent": quote.get("change_percent"),
                "has_user_rule": symbol in profile_symbols,
            }
        )
    return {
        "analysis_mode": "full",
        "holding_count": len(holdings),
        "live_quote_count": live_quote_count,
        "holdings": holdings,
    }


def _portfolio_summary(snapshot: dict[str, Any], store: Store) -> dict[str, Any]:
    fx = get_rates_to_cny()
    rates = fx["rates_to_cny"]
    store.record_fx_rates(
        rates,
        provider=fx["provider"],
        observed_at=datetime.fromisoformat(fx["observed_at"]),
    )
    total_cny = 0.0
    by_currency: dict[str, float] = {}
    by_theme: dict[str, float] = {}
    for holding in snapshot.get("holdings", []):
        if float(holding.get("quantity") or 0) <= 0:
            continue
        live_market_value = holding.get("live_market_value")
        value = float(live_market_value if live_market_value is not None else holding.get("market_value") or 0)
        if value <= 0:
            continue
        currency = str(holding.get("currency", "USD"))
        cny = value * rates.get(currency, 1)
        total_cny += cny
        by_currency[currency] = by_currency.get(currency, 0) + value
        theme = str(holding.get("theme") or "未分类")
        by_theme[theme] = by_theme.get(theme, 0) + cny
    concentration = [
        {"theme": theme, "value_cny": round(value, 2), "weight_percent": round(value / total_cny * 100, 2)}
        for theme, value in sorted(by_theme.items(), key=lambda item: item[1], reverse=True)
    ] if total_cny else []
    return {
        "estimated_total_cny": round(total_cny, 2),
        "original_currency_values": {key: round(value, 2) for key, value in by_currency.items()},
        "fx": fx,
        "theme_concentration": concentration,
    }


def _start_scheduler(store: Store) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        lambda: refresh_decisions(store, enrich=False, source="risk_monitor"),
        IntervalTrigger(minutes=15),
        id="decision-risk-monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: _run_due_market_analysis(store),
        IntervalTrigger(minutes=5),
        id="market-analysis-dispatcher",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler


def _analysis_settings_payload(store: Store, *, now: datetime | None = None) -> dict[str, Any]:
    settings = store.analysis_settings()
    last_analysis = store.latest_completed_sync("market_analysis")
    return settings | schedule_status(settings, last_analysis_at=last_analysis, now=now)


def _risk_configuration_payload(store: Store) -> dict[str, Any]:
    snapshot = store.latest_snapshot()
    holdings = [] if snapshot is None else [
        {
            "symbol": str(item["symbol"]).upper(),
            "name": str(item.get("name") or item["symbol"]),
            "market": item.get("market"),
            "security_type": item.get("security_type", "stock"),
            "quantity": item.get("quantity", 0),
        }
        for item in snapshot.get("holdings", [])
        if float(item.get("quantity") or 0) > 0
    ]
    profiles = store.risk_profiles()
    return {
        **store.risk_settings(),
        "holdings": holdings,
        "profiles": profiles,
        "active_profile_count": sum(1 for item in profiles if item["status"] == "active"),
        "inactive_profile_count": sum(1 for item in profiles if item["status"] != "active"),
        "system_suggestions": [],
    }


def _run_due_market_analysis(store: Store, *, now: datetime | None = None) -> dict[str, Any]:
    status = _analysis_settings_payload(store, now=now)
    if not status["enabled_current_sessions"]:
        return {"status": "outside_enabled_session", "schedule": status}
    if not status["due"]:
        return {"status": "not_due", "schedule": status}
    result = refresh_decisions(store, notify=True, enrich=True, source="market_analysis")
    return {
        "status": "completed",
        "decision_count": len(result.decisions),
        "model_status": result.model_status,
        "schedule": status,
    }


def _safe_database_label(url: str) -> str:
    return "sqlite" if url.startswith("sqlite") else url.split(":", 1)[0]


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run("trading_assistant.api:app", host=host, port=port, reload=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-assistant-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

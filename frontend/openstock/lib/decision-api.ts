export type DataQuality = {
    provider: string;
    observed_at?: string | null;
    freshness_seconds?: number | null;
    source_type: "live" | "snapshot" | "fallback" | "derived" | "unavailable";
    actionable: boolean;
    usage: "execution" | "monitoring" | "reference" | "unavailable";
    market_status: "open" | "closed" | "unknown";
    execution_ready: boolean;
    issues: string[];
};

export type Evidence = {
    kind: string;
    title: string;
    detail: string;
    source_url?: string | null;
    observed_at?: string | null;
};

export type Decision = {
    id: string;
    symbol: string;
    name: string;
    title: string;
    summary: string;
    action: "verify" | "hold" | "reduce" | "exit" | "add" | "watch";
    priority: "urgent" | "high" | "normal" | "opportunity";
    current_weight_percent?: number | null;
    target_weight_percent?: number | null;
    quantity_delta?: number | null;
    trigger: string;
    invalid_if: string;
    current_limit: string;
    policy_response: "review" | "stop_adding" | "reduce" | "exit";
    event_classification: "value_event" | "sentiment_liquidity" | "mixed" | "unexplained" | "not_applicable";
    information_grade: "A" | "B" | "C" | "unrated";
    research_confidence: "high" | "medium" | "low" | "unrated";
    investment_certainty: "high" | "medium" | "low" | "unrated";
    confidence: "high" | "medium" | "low";
    data_quality: DataQuality;
    evidence: Evidence[];
    order_draft?: {
        symbol: string;
        side: "buy" | "sell";
        quantity: number;
        limit_price_low: number;
        limit_price_high: number;
        valid_until: string;
        executable: false;
    } | null;
    generated_at: string;
    expires_at: string;
    status: string;
};

export type Holding = {
    symbol: string;
    name: string;
    market: "US" | "HK" | "CN";
    security_type: string;
    quantity: number;
    available_quantity?: number;
    currency: "USD" | "HKD" | "CNY";
    market_value: number;
    live_market_value?: number | null;
    screenshot_price?: number;
    price?: number;
    live_price?: number | null;
    average_cost: number;
    holding_pnl?: number;
    holding_pnl_percent?: number;
    theme?: string;
    display_price_source?: string;
    live_quote?: Record<string, unknown>;
};

export type SnapshotMeta = {
    status: "confirmed" | "missing";
    as_of?: string;
    source?: string;
    age_seconds?: number;
    holding_count?: number;
    quote_summary?: { total: number; live: number; fallback: number; status: string };
};

export type PortfolioSummary = {
    estimated_total_cny: number;
    original_currency_values: Record<string, number>;
    fx: { rates_to_cny: Record<string, number>; provider: string; actionable: boolean };
    theme_concentration: Array<{ theme: string; value_cny: number; weight_percent: number }>;
};

export type DashboardPayload = {
    generated_at: string;
    snapshot: SnapshotMeta;
    account: Record<string, number | string>;
    summary: PortfolioSummary;
    decisions: Decision[];
    stable_holdings: Holding[];
    next_runs: string[];
};

export type HoldingsPayload = {
    snapshot: SnapshotMeta;
    account: Record<string, number | string>;
    summary: PortfolioSummary;
    holdings: Holding[];
};

export type AnalysisSettings = {
    interval_minutes: number;
    analyze_us_premarket: boolean;
    analyze_regular_session: boolean;
    analyze_us_afterhours: boolean;
    updated_at: string;
    current_sessions: string[];
    enabled_current_sessions: string[];
    last_analysis_at?: string | null;
    next_due_at?: string | null;
    due: boolean;
    dispatcher_interval_minutes: number;
};

export type HoldingRiskProfile = {
    symbol: string;
    stop_price?: number | null;
    target_weight_percent?: number | null;
    thesis_invalidation: string;
    thesis_summary: string;
    information_grade: "A" | "B" | "C" | "unrated";
    research_confidence: "high" | "medium" | "low" | "unrated";
    investment_certainty: "high" | "medium" | "low" | "unrated";
    strongest_bear_case: string;
    buy_add_conditions: string;
    reduce_conditions: string;
    exit_invalidation_conditions: string;
    bear_scenario: string;
    base_scenario: string;
    bull_scenario: string;
    position_intent: "long_term" | "tactical" | "derivative";
    price_response: "review" | "stop_adding" | "reduce" | "exit";
    expiry_date?: string | null;
    status: "active" | "inactive_cleared" | "disabled_by_user";
    source: string;
    updated_at: string;
};

export type InvestmentPolicy = {
    version: string;
    name: string;
    principles: string[];
    research: {
        thesis: string[];
        information_grades: Record<"A" | "B" | "C", string>;
        counter_case: string[];
    };
    scenarios: { required: string[]; rule: string };
    entry_and_add: string[];
    review: {
        clean_slate: string;
        event_classes: Record<string, string>;
        responses: Record<string, string>;
    };
    instrument_rules: Record<string, string>;
    exit_reasons: string[];
};

export type RiskConfiguration = {
    max_single_position_percent: number;
    daily_move_alert_percent: number;
    warrant_expiry_warning_days: number;
    target_weight_tolerance_percent: number;
    updated_at: string;
    holdings: Array<{ symbol: string; name: string; market: string; security_type: string; quantity: number }>;
    profiles: HoldingRiskProfile[];
    active_profile_count: number;
    inactive_profile_count: number;
    system_suggestions: unknown[];
};

export type DecisionRefreshResponse = {
    status: "refreshed";
    decisions: Decision[];
    summary: {
        checked_holdings: number;
        generic_rules: number;
        active_user_rules: number;
        decision_count: number;
        model_status: "used" | "skipped_no_decisions" | "skipped_not_configured" | "skipped_lightweight" | "failed_fallback";
        completed_at: string;
    };
};

export type Opportunity = {
    symbol: string;
    name: string;
    market: string;
    thesis: string;
    price?: number | null;
    regular_price?: number | null;
    market_session?: string | null;
    change_percent?: number | null;
    status: string;
    data_quality: DataQuality;
    trend_30: number[];
    trend_90: number[];
};

export const apiBase = process.env.NEXT_PUBLIC_TRADING_ASSISTANT_API_URL
    ?? (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8765" : "");

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${apiBase}${path}`, { cache: "no-store", ...init });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `请求失败 (${response.status})`);
    }
    return response.json() as Promise<T>;
}

export function formatMoney(value: number, currency = "CNY") {
    return new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
    }).format(value);
}

export function relativeTime(value?: string) {
    if (!value) return "未知";
    const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 60) return `${seconds} 秒前`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟前`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时前`;
    return `${Math.round(seconds / 86400)} 天前`;
}

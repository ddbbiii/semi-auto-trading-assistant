"use client";

import { useEffect, useState } from "react";
import {
    AlertTriangle, ArrowDownRight, Check, ChevronDown, Clock3, Database, RefreshCw, ShieldAlert, TimerReset, X,
} from "lucide-react";
import { apiFetch, DashboardPayload, Decision, DecisionRefreshResponse, formatMoney, Holding, relativeTime } from "@/lib/decision-api";

const actionCopy = {
    verify: "需要核验", hold: "继续持有", reduce: "考虑减仓", exit: "复核退出", add: "分批增加", watch: "继续观察",
};

const evidenceKindCopy: Record<string, string> = {
    price: "价格", position: "持仓", risk_rule: "风控规则", filing: "公告", news: "新闻", system: "数据状态",
};

const responseCopy: Record<Decision["policy_response"], string> = {
    review: "复核", stop_adding: "暂停加仓", reduce: "减仓检查", exit: "退出",
};
const confidenceCopy = { high: "高", medium: "中", low: "低", unrated: "未评定" };

const internalCodeCopy: Record<string, string> = {
    quote_stale: "行情超过当前场景允许的监控时限，系统将通过 API 自动重试",
    quote_delayed: "行情有短暂延迟，但仍可用于日常风险监控",
    market_closed_reference: "当前已闭市，使用最近交易时段行情作为风险参考",
    extended_hours_monitoring: "当前为美股盘前或盘后，行情仅用于观察，不生成具体限价草案",
    extended_quote_unavailable: "暂未取得当前盘前或盘后价格，正常收盘价不会冒充实时行情",
    two_sided_quote_unavailable: "暂未取得新鲜双边盘口，不生成具体限价草案",
    live_quote_unavailable: "暂时无法取得可靠的实时行情",
    portfolio_snapshot_stale: "账户持仓超过二十四小时未确认",
    quote_above_stop: "当前价格尚未触及风险线",
    official_news_unverified: "最新官方公告和重要信息尚未完成核验",
};

export default function DecisionWorkbench() {
    const [data, setData] = useState<DashboardPayload | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState("");
    const [receipt, setReceipt] = useState<DecisionRefreshResponse["summary"] | null>(null);

    const load = async (background = false) => {
        if (background) setRefreshing(true);
        else setLoading(true);
        try {
            setData(await apiFetch<DashboardPayload>("/api/v1/dashboard"));
            setError("");
        } catch (cause) { setError(cause instanceof Error ? cause.message : "决策台加载失败"); }
        finally { setLoading(false); setRefreshing(false); }
    };

    useEffect(() => {
        void load();
        const timer = window.setInterval(() => void load(true), 5 * 60_000);
        return () => window.clearInterval(timer);
    }, []);

    const refreshDecisions = async () => {
        setRefreshing(true);
        try {
            const result = await apiFetch<DecisionRefreshResponse>("/api/v1/decisions/refresh", { method: "POST" });
            setReceipt(result.summary);
            await load(true);
        } catch (cause) { setError(cause instanceof Error ? cause.message : "重新计算失败"); setRefreshing(false); }
    };

    if (loading && !data) return <PageLoading />;
    if (!data) return <EmptyError message={error} onRetry={() => void load()} />;

    const quote = data.snapshot.quote_summary;
    return <div className="page-stack">
        <section className="page-intro decision-intro">
            <div><p className="eyebrow">TODAY&apos;S DECISIONS</p><h1>今天该做什么</h1><p>风险事项优先。没有可靠数据时，系统只要求核验，不给出伪精确的交易数量。</p></div>
            <button type="button" className="refresh-button" disabled={refreshing} onClick={() => void refreshDecisions()}><RefreshCw className={refreshing ? "spin" : ""} size={17} />{refreshing ? "正在检查全部持仓" : "重新计算"}</button>
        </section>

        <section className="status-rail" aria-label="数据状态">
            <StatusItem icon={<Database />} label="账户快照" value={data.snapshot.status === "fresh" ? "可用" : "已过期"} detail={relativeTime(data.snapshot.as_of)} tone={data.snapshot.status === "fresh" ? "good" : "warn"} />
            <StatusItem icon={<TimerReset />} label="实时行情" value={`${quote?.live ?? 0}/${quote?.total ?? 0}`} detail={`${quote?.fallback ?? 0} 个使用兜底`} tone={quote?.status === "ok" ? "good" : "warn"} />
            <StatusItem icon={<Clock3 />} label="检查范围" value="全部持仓" detail="通用规则 + 用户规则" tone="neutral" />
            <div className="status-total"><span>组合估值</span><strong>{formatMoney(data.summary.estimated_total_cny)}</strong><small>按参考汇率估算</small></div>
        </section>

        {error ? <p className="error-banner">{error}</p> : null}
        {receipt ? <CalculationReceipt receipt={receipt} /> : null}

        <section className="decision-section">
            <div className="section-heading"><div><span className="section-index">01</span><div><h2>决策收件箱</h2><p>最多保留三件当前真正需要处理的事</p></div></div><span className="count-chip">{data.decisions.length}</span></div>
            <div className="decision-list">
                {data.decisions.length ? data.decisions.map((decision, index) => <DecisionCard key={decision.id} decision={decision} rank={index + 1} onChanged={() => void load(true)} />) : <div className="clear-state"><Check /><strong>当前没有需要处理的动作</strong><span>系统仍会持续检查行情、公告和风险线。</span></div>}
            </div>
        </section>

        <details className="stable-section">
            <summary><div><span className="section-index">02</span><div><h2>稳定持仓</h2><p>{data.stable_holdings.length} 个持仓暂时无需动作</p></div></div><ChevronDown /></summary>
            <div className="stable-grid">{data.stable_holdings.map((holding) => <HoldingMini key={holding.symbol} holding={holding} />)}</div>
        </details>
    </div>;
}

function CalculationReceipt({ receipt }: { receipt: DecisionRefreshResponse["summary"] }) {
    const modelLabel = {
        used: "模型已解释触发事项",
        skipped_no_decisions: "无触发事项，模型未调用",
        skipped_not_configured: "模型未配置，保留规则结果",
        skipped_lightweight: "轻量检查未调用模型",
        failed_fallback: "模型调用失败，已保留规则结果",
    }[receipt.model_status];
    return <div className="calculation-receipt"><Check /><span><strong>计算完成</strong><small>检查 {receipt.checked_holdings} 个持仓 · {receipt.generic_rules} 条通用规则 · {receipt.active_user_rules} 组用户规则 · 触发 {receipt.decision_count} 项</small></span><em>{modelLabel} · {new Date(receipt.completed_at).toLocaleTimeString("zh-CN", { hour12: false })}</em></div>;
}

function DecisionCard({ decision, rank, onChanged }: { decision: Decision; rank: number; onChanged: () => void }) {
    const [feedback, setFeedback] = useState<"executed" | "snoozed" | "rejected" | null>(null);
    const [busy, setBusy] = useState(false);
    const [quantity, setQuantity] = useState(decision.order_draft?.quantity?.toString() || "");
    const [price, setPrice] = useState("");
    const [note, setNote] = useState("");
    const qualityLabel = decision.data_quality.execution_ready
        ? "盘口已就绪"
        : decision.data_quality.usage === "reference"
            ? "收盘价参考"
            : decision.data_quality.actionable
                ? "行情可监控"
                : "数据暂不可用";

    const submit = async () => {
        if (!feedback) return;
        setBusy(true);
        try {
            await apiFetch(`/api/v1/decisions/${decision.id}/feedback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: feedback,
                    executed_quantity: feedback === "executed" && quantity ? Number(quantity) : null,
                    executed_price: feedback === "executed" && price ? Number(price) : null,
                    note: note || null,
                }),
            });
            onChanged();
        } finally { setBusy(false); }
    };

    return <article className={`decision-card priority-${decision.priority}`}>
        <div className="decision-rank">{String(rank).padStart(2, "0")}</div>
        <div className="decision-body">
            <div className="decision-topline">
                <div className="decision-symbol">
                    <span className="decision-identity"><code>{decision.symbol}</code><strong>{decision.name || decision.symbol}</strong></span>
                    <small>{actionCopy[decision.action]}</small>
                </div>
                <div className={`quality-badge ${decision.data_quality.actionable ? "actionable" : "blocked"}`}>{decision.data_quality.actionable ? <Check /> : <ShieldAlert />}{qualityLabel}</div>
            </div>
            <h3>{decision.title}</h3><p className="decision-summary">{decision.summary}</p>
            <div className="decision-policy-strip">
                <span>响应级别 <strong>{responseCopy[decision.policy_response]}</strong></span>
                <span>证据等级 <strong>{decision.information_grade === "unrated" ? "未评定" : decision.information_grade}</strong></span>
                <span>研究置信度 <strong>{confidenceCopy[decision.research_confidence]}</strong></span>
                <span>投资确定性 <strong>{confidenceCopy[decision.investment_certainty]}</strong></span>
            </div>
            <div className="decision-numbers">
                <NumberCell label={decision.data_quality.actionable ? "当前仓位" : "估算仓位"} value={decision.current_weight_percent == null ? "—" : `${decision.current_weight_percent}%`} />
                <NumberCell label="目标仓位" value={decision.target_weight_percent == null ? "暂不计算" : `${decision.target_weight_percent}%`} />
                <NumberCell label="数量变化" value={decision.quantity_delta == null ? "暂不计算" : `${decision.quantity_delta > 0 ? "+" : ""}${decision.quantity_delta}`} />
                <NumberCell label="有效期" value={new Date(decision.expires_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} />
            </div>
            <div className="condition-grid"><div><span>{decision.data_quality.actionable ? "触发依据" : "恢复计算需要"}</span><p>{humanize(decision.trigger)}</p></div><div><span>当前限制</span><p>{humanize(decision.current_limit || "无额外限制")}</p></div><div><span>失效条件</span><p>{humanize(decision.invalid_if)}</p></div></div>
            {decision.order_draft ? <div className="order-draft"><ArrowDownRight /><div><strong>限价草案：卖出 {decision.order_draft.quantity}</strong><span>{decision.order_draft.limit_price_low}–{decision.order_draft.limit_price_high} · 仅供复制，不会自动提交</span></div></div> : null}
            <details className="evidence"><summary>查看 {decision.evidence.length} 条判断依据<ChevronDown /></summary><div>{decision.evidence.map((item, index) => <div className="evidence-row" key={`${item.title}-${index}`}><span>{evidenceKindCopy[item.kind] || "依据"}</span><p><strong>{item.title}</strong>{humanize(item.detail)}</p></div>)}</div></details>
            <div className="decision-actions">
                <button className="done" onClick={() => setFeedback("executed")}><Check />已执行</button>
                <button onClick={() => setFeedback("snoozed")}><Clock3 />稍后</button>
                <button onClick={() => setFeedback("rejected")}><X />否决</button>
            </div>
            {feedback ? <div className="feedback-form">
                <div className="feedback-title"><strong>{feedback === "executed" ? "记录实际执行" : feedback === "snoozed" ? "稍后处理" : "否决建议"}</strong><button onClick={() => setFeedback(null)}><X /></button></div>
                {feedback === "executed" ? <div className="feedback-fields"><label>数量<input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="decimal" /></label><label>成交价<input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" /></label></div> : null}
                <label>备注（可选）<textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} /></label>
                <button className="primary-button" disabled={busy} onClick={() => void submit()}>{busy ? "保存中…" : "确认记录"}</button>
            </div> : null}
        </div>
    </article>;
}

function StatusItem({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: string }) {
    return <div className={`status-item ${tone}`}><span className="status-icon">{icon}</span><div><small>{label}</small><strong>{value}</strong><span>{detail}</span></div></div>;
}

function NumberCell({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function humanize(value: string) {
    return Object.entries(internalCodeCopy).reduce((result, [code, copy]) => result.replaceAll(code, copy), value);
}

function HoldingMini({ holding }: { holding: Holding }) {
    const value = holding.live_market_value ?? holding.market_value;
    const price = holding.live_price ?? holding.screenshot_price ?? holding.price;
    return <div className="holding-mini"><div><strong>{holding.symbol}</strong><span>{holding.name}</span></div><div><strong>{formatMoney(value, holding.currency)}</strong><span>{price ?? "—"} · {holding.display_price_source === "live_quote" ? "实时" : "快照"}</span></div></div>;
}

function PageLoading() { return <div className="page-loading"><RefreshCw className="spin" /><strong>正在建立今天的决策上下文</strong><span>同步账户、行情和风险状态…</span></div>; }
function EmptyError({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="fatal-state"><AlertTriangle /><h1>决策台暂不可用</h1><p>{message}</p><button className="primary-button" onClick={onRetry}>重试</button></div>; }

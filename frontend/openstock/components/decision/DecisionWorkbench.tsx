"use client";

import { useEffect, useState } from "react";
import {
    Activity, AlertTriangle, ArrowDownRight, Check, ChevronDown, Clock3, Database, Lightbulb,
    RefreshCw, Scale, ShieldAlert, Sparkles, TimerReset, X,
} from "lucide-react";
import { AnalysisReport, AnalysisTone, apiFetch, DashboardPayload, DataCoverageItem, Decision, DecisionRefreshResponse, formatMoney, Holding, LlmStatus, relativeTime } from "@/lib/decision-api";

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
    quote_above_stop: "当前价格尚未触及风险线",
    official_news_unverified: "最新官方公告和重要信息尚未完成核验",
};

export default function DecisionWorkbench() {
    const [data, setData] = useState<DashboardPayload | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState("");
    const [receipt, setReceipt] = useState<DecisionRefreshResponse["summary"] | null>(null);
    const [testingModel, setTestingModel] = useState(false);

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

    const testModel = async () => {
        setTestingModel(true);
        setError("");
        try {
            const llm = await apiFetch<LlmStatus>("/api/v1/system/test-llm", { method: "POST" });
            setData((current) => current ? { ...current, llm } : current);
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : "模型 API 测试失败");
        } finally {
            setTestingModel(false);
        }
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
            <StatusItem icon={<Database />} label="持仓基线" value={data.snapshot.status === "confirmed" ? "已确认" : "尚未建立"} detail={data.snapshot.as_of ? `最近确认 ${relativeTime(data.snapshot.as_of)}` : "请先导入持仓"} tone={data.snapshot.status === "confirmed" ? "good" : "warn"} />
            <StatusItem icon={<TimerReset />} label="实时行情" value={`${quote?.live ?? 0}/${quote?.total ?? 0}`} detail={`${quote?.fallback ?? 0} 个使用兜底`} tone={quote?.status === "ok" ? "good" : "warn"} />
            <StatusItem icon={<Clock3 />} label="检查范围" value="全部持仓" detail="通用规则 + 用户规则" tone="neutral" />
            <div className="status-total"><span>组合估值</span><strong>{formatMoney(data.summary.estimated_total_cny)}</strong><small>按参考汇率估算</small></div>
        </section>

        <ModelApiAlert status={data.llm} testing={testingModel} onTest={() => void testModel()} />
        {error ? <p className="error-banner">{error}</p> : null}
        {receipt ? <CalculationReceipt receipt={receipt} modelStatus={data.llm} retrying={refreshing} onRetry={() => void refreshDecisions()} /> : null}

        <section className="decision-section">
            <div className="section-heading"><div><span className="section-index">01</span><div><h2>决策收件箱</h2><p>最多保留三件当前真正需要处理的事</p></div></div><span className="count-chip">{data.decisions.length}</span></div>
            <div className="decision-list">
                {data.decisions.length ? data.decisions.map((decision, index) => <DecisionCard key={decision.id} decision={decision} rank={index + 1} onChanged={() => void load(true)} />) : <div className="clear-state"><Check /><strong>当前没有需要处理的动作</strong><span>系统仍会持续检查行情、公告和风险线。</span></div>}
            </div>
        </section>

        <AnalysisReportPanel report={data.analysis_report} refreshing={refreshing} onRefresh={() => void refreshDecisions()} />

        <details className="stable-section">
            <summary><div><span className="section-index">03</span><div><h2>稳定持仓</h2><p>{data.stable_holdings.length} 个持仓暂时无需动作</p></div></div><ChevronDown /></summary>
            <div className="stable-grid">{data.stable_holdings.map((holding) => <HoldingMini key={holding.symbol} holding={holding} />)}</div>
        </details>
    </div>;
}

function AnalysisReportPanel({ report, refreshing, onRefresh }: { report?: AnalysisReport | null; refreshing: boolean; onRefresh: () => void }) {
    if (!report) {
        return <section className="analysis-report-section empty">
            <div className="section-heading"><div><span className="section-index">02</span><div><h2>为什么得出这个结论</h2><p>完整分析会在这里保留事实、判断链和反方条件</p></div></div></div>
            <div className="analysis-empty"><Lightbulb /><strong>还没有可展示的完整分析</strong><span>执行一次“重新计算”后，报告会持久保留在这里。</span><button type="button" className="primary-button" disabled={refreshing} onClick={onRefresh}>{refreshing ? "分析中…" : "生成完整分析"}</button></div>
        </section>;
    }
    const source = report.source === "manual_decision" ? "手动全量分析" : report.source === "scheduled_decision" ? "两小时自动分析" : "完整分析";
    const modelUsed = report.model_status === "used";
    return <section className="analysis-report-section">
        <div className="section-heading analysis-report-heading"><div><span className="section-index">02</span><div><h2>为什么得出这个结论</h2><p>把事实、推断和限制分开，便于复核而不是只看一句建议</p></div></div><span className={`analysis-source ${modelUsed ? "model" : "local"}`}>{modelUsed ? <Sparkles /> : <Activity />}{source} · {relativeTime(report.generated_at)}</span></div>
        <div className="analysis-conclusion">
            <span>本次结论</span>
            <h3>{report.headline}</h3>
            <p>{report.conclusion}</p>
        </div>
        {(report.data_coverage?.length ?? 0) > 0 ? <AnalysisCoverage items={report.data_coverage ?? []} /> : null}
        <div className="analysis-columns">
            <AnalysisBlock icon={<Activity />} eyebrow="FACTS" title="关键事实" items={report.market_facts.map((item) => ({ label: item.label, detail: item.detail, tone: item.tone }))} />
            <AnalysisBlock icon={<Lightbulb />} eyebrow="REASONING" title="判断链" items={report.reasoning.map((item) => ({ label: item.title, detail: item.detail, tone: item.tone }))} />
        </div>
        {report.position_notes.length ? <div className="position-analysis">
            <div className="analysis-subheading"><div><Scale /><span><strong>逐标的处理</strong><small>动作来自本地规则，模型只补充原因</small></span></div><em>{report.position_notes.length} 个标的</em></div>
            <div className="position-analysis-list">{report.position_notes.map((item) => <article className={`position-analysis-row tone-${item.tone}`} key={item.symbol}><div className="position-analysis-id"><code>{item.symbol}</code><span>{item.name}</span></div><strong>{item.stance}</strong><p>{item.reason}</p></article>)}</div>
        </div> : null}
        {(report.counterpoints.length || report.limitations.length) ? <div className="analysis-caveats">
            {report.counterpoints.length ? <div className="counterpoint"><ShieldAlert /><span><strong>最强反方</strong>{report.counterpoints.map((item) => <p key={item}>{item}</p>)}</span></div> : null}
            {report.limitations.length ? <div className="limitation"><AlertTriangle /><span><strong>当前限制</strong>{report.limitations.map((item) => <p key={item}>{item}</p>)}</span></div> : null}
        </div> : null}
    </section>;
}

function AnalysisCoverage({ items }: { items: DataCoverageItem[] }) {
    const statusCopy = { available: "已同步", derived: "已计算", partial: "部分覆盖", missing: "缺失" };
    return <section className="analysis-coverage">
        <header><div><Database /><span><strong>本次分析用了什么数据</strong><small>后端权威覆盖率，模型不能自行改写</small></span></div><em>原始金额与数量不发送给模型</em></header>
        <div className="analysis-coverage-grid">{items.map((item) => <article className={`coverage-item ${item.status}`} key={item.key} title={item.detail}>
            <span>{item.label}</span>
            <strong>{statusCopy[item.status]}</strong>
            <small>{item.available}/{item.total}</small>
            <p>{item.detail}</p>
        </article>)}</div>
    </section>;
}

function AnalysisBlock({ icon, eyebrow, title, items }: { icon: React.ReactNode; eyebrow: string; title: string; items: Array<{ label: string; detail: string; tone: AnalysisTone }> }) {
    return <section className="analysis-block"><header><span>{icon}</span><div><small>{eyebrow}</small><strong>{title}</strong></div></header><div className="analysis-point-list">{items.map((item, index) => <article className={`analysis-point tone-${item.tone}`} key={`${item.label}-${index}`}><mark>{item.label}</mark><p>{item.detail}</p></article>)}</div></section>;
}

function CalculationReceipt({ receipt, modelStatus, retrying, onRetry }: { receipt: DecisionRefreshResponse["summary"]; modelStatus?: LlmStatus; retrying: boolean; onRetry: () => void }) {
    const marketState = receipt.market_data_status === "success" ? "success" : receipt.market_data_status === "partial" ? "partial" : "failed";
    const officialState = receipt.official_evidence_status === "ok" ? "success" : receipt.official_evidence_status === "partial" ? "partial" : "failed";
    const modelFailed = modelStatus?.connectivity === "error" || modelStatus?.test === "failed" || receipt.model_status === "failed_fallback" || receipt.model_status === "skipped_not_configured";
    const modelState = receipt.model_status === "used" ? "success" : modelFailed ? "failed" : "not_called";
    const overallWarning = marketState !== "success" || officialState !== "success" || modelState === "failed";
    const modelDetail = receipt.model_status === "used"
        ? receipt.model_summary || "模型 API 已完成本次完整分析。"
        : modelFailed
            ? modelStatus?.message || "模型 API 调用失败，已保留确定性规则结果。"
            : receipt.model_status === "skipped_lightweight"
                ? "本次属于 15 分钟轻量监控，按设置不调用模型 API。"
                : "当前回执来自旧版跳过逻辑，请重新执行完整分析。";
    return <div className={`calculation-receipt ${overallWarning ? "warning" : ""}`} role={overallWarning ? "alert" : undefined}>
        <div className="calculation-receipt-heading"><Check /><span><strong>计算完成</strong><small>检查 {receipt.checked_holdings} 个持仓 · 全局规则已应用 · {receipt.active_user_rules} 组可选覆盖 · 触发 {receipt.decision_count} 项</small></span><em>{new Date(receipt.completed_at).toLocaleTimeString("zh-CN", { hour12: false })}</em></div>
        <div className="calculation-channel-grid">
            <section className="calculation-channel-group"><strong>后端与数据 API</strong><ChannelLine label="后端重算 API" state="success" detail="已完成全局规则检查" /><ChannelLine label="行情 API" state={marketState} detail={`${receipt.market_data_live}/${receipt.market_data_total} 条行情可用${receipt.market_data_fallback ? `，${receipt.market_data_fallback} 条使用备用源` : ""}`} /><ChannelLine label="官方公告 API" state={officialState} detail={`${receipt.official_evidence_checked}/${receipt.official_evidence_total} 个标的已检查，取得 ${receipt.official_evidence_documents} 条近期文件`} /></section>
            <section className="calculation-channel-group"><strong>大模型 API</strong><ChannelLine label={modelState === "not_called" ? "本次未调用" : modelState === "success" ? "调用成功" : "调用失败"} state={modelState} detail={modelDetail} />{modelState !== "success" ? <button className="calculation-channel-action" type="button" disabled={retrying} onClick={onRetry}>{retrying ? "完整分析中…" : "重新执行完整分析"}</button> : null}</section>
        </div>
    </div>;
}

function ChannelLine({ label, state, detail }: { label: string; state: "success" | "partial" | "not_called" | "failed"; detail: string }) {
    const Icon = state === "success" ? Check : state === "failed" ? AlertTriangle : Clock3;
    const stateLabel = state === "success" ? "成功" : state === "partial" ? "部分可用" : state === "failed" ? "失败" : "未调用";
    return <div className={`channel-line ${state}`}><Icon /><span><strong>{label}</strong><small>{stateLabel} · {detail}</small></span></div>;
}

function ModelApiAlert({ status, testing, onTest }: { status?: LlmStatus; testing: boolean; onTest: () => void }) {
    if (!status) return null;
    const failed = status.status === "not_configured" || status.connectivity === "error";
    if (!failed) return null;
    const title = status.status === "not_configured" ? "大模型 API 尚未配置" : "大模型 API 最近调用失败";
    return <div className="system-alert" role="alert"><AlertTriangle /><div><strong>{title}</strong><span>{status.message} 当前只保留确定性规则结果，不会假装模型已经提供解释。</span></div><button type="button" disabled={testing} onClick={onTest}>{testing ? "测试中…" : "测试连接"}</button><a href="/settings#model-api">查看设置</a></div>;
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
                <NumberCell label="当前权重" value={decision.current_weight_percent == null ? "—" : `${decision.current_weight_percent}%`} />
                <NumberCell label="目标仓位" value={decision.target_weight_percent == null ? "暂不计算" : `${decision.target_weight_percent}%`} />
                <NumberCell label="数量变化" value={decision.quantity_delta == null ? "暂不计算" : `${decision.quantity_delta > 0 ? "+" : ""}${decision.quantity_delta}`} />
                <NumberCell label="有效期" value={new Date(decision.expires_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} />
            </div>
            <div className="condition-grid"><div><span>{decision.data_quality.actionable ? "触发依据" : "恢复计算需要"}</span><p>{humanize(decision.trigger)}</p></div><div><span>当前限制</span><p>{humanize(decision.current_limit || "无额外限制")}</p></div><div><span>失效条件</span><p>{humanize(decision.invalid_if)}</p></div></div>
            {decision.order_draft ? <div className="order-draft"><ArrowDownRight /><div><strong>限价草案：卖出 {decision.order_draft.quantity}</strong><span>{decision.order_draft.limit_price_low}–{decision.order_draft.limit_price_high} · 仅供复制，不会自动提交</span></div></div> : null}
            <details className="evidence"><summary>查看 {decision.evidence.length} 条判断依据<ChevronDown /></summary><div>{decision.evidence.map((item, index) => <div className="evidence-row" key={`${item.title}-${index}`}><span>{evidenceKindCopy[item.kind] || "依据"}</span><p>{item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.title}</a> : <strong>{item.title}</strong>}{humanize(item.detail)}</p></div>)}</div></details>
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

"use client";

import { useEffect, useState } from "react";
import { Activity, ChevronDown, CircleAlert, Database, RefreshCw } from "lucide-react";
import { apiFetch, Opportunity, relativeTime } from "@/lib/decision-api";

const issueCopy: Record<string, string> = {
    quote_stale: "行情超过当前监控时限，系统会自动重试",
    quote_delayed: "行情有短暂延迟，仍可用于日常观察",
    market_closed_reference: "当前已闭市，使用最近交易时段行情作为参考",
    extended_hours_monitoring: "当前为盘前或盘后行情，仅用于观察，不生成限价草案",
    extended_quote_unavailable: "暂未取得当前盘前或盘后价格，正常收盘价不会冒充实时行情",
    two_sided_quote_unavailable: "暂未取得新鲜双边盘口，不生成限价草案",
    live_quote_unavailable: "行情接口暂时没有返回有效报价",
};

export default function OpportunitiesWorkbench() {
    const [items, setItems] = useState<Opportunity[] | null>(null);
    const [error, setError] = useState("");
    useEffect(() => { void apiFetch<{ items: Opportunity[] }>("/api/v1/opportunities").then((data) => setItems(data.items)).catch((e) => setError(e.message)); }, []);
    if (!items) return <div className="page-loading">{error ? <><CircleAlert /><strong>{error}</strong></> : <><RefreshCw className="spin" /><strong>正在检查候选机会…</strong></>}</div>;
    return <div className="page-stack"><section className="page-intro"><div><p className="eyebrow">OPPORTUNITIES</p><h1>等待赔率改善</h1><p>机会与持仓风险分开。只有价格、趋势和数据质量同时满足，候选才会进入可操作状态。</p></div><span className="snapshot-chip fresh">{items.length} 个观察标的</span></section>
        <section className="opportunity-grid">{items.map((item) => <OpportunityCard key={item.symbol} item={item} />)}</section></div>;
}

function OpportunityCard({ item }: { item: Opportunity }) {
    const [expanded, setExpanded] = useState(false);
    const evidenceId = `opportunity-evidence-${item.symbol.replaceAll(".", "-")}`;
    const issues = item.data_quality.issues.map((issue) => issueCopy[issue] ?? issue);

    return <article className={`opportunity-card ${expanded ? "expanded" : ""}`}>
        <div className="opportunity-head"><div><span>{item.market}</span><strong>{item.symbol}</strong><small>{item.name}</small></div><div className={`quality-dot ${item.data_quality.actionable ? "good" : "warn"}`} title={issues.join("、")} /></div>
        <div className="opportunity-price"><span>{item.price ?? "—"}</span><small className={(item.change_percent ?? 0) >= 0 ? "positive" : "negative"}>{item.change_percent == null ? "等待行情" : `${item.change_percent > 0 ? "+" : ""}${item.change_percent.toFixed(2)}%`}</small></div>
        <MiniTrend seed={item.symbol} />
        <p className="opportunity-thesis">{item.thesis}</p>
        <div className="opportunity-foot"><span><Activity />{item.status}</span><button type="button" aria-expanded={expanded} aria-controls={evidenceId} onClick={() => setExpanded((value) => !value)}>{expanded ? "收起依据" : "展开依据"}<ChevronDown className={expanded ? "expanded" : ""} /></button></div>
        <div id={evidenceId} className={`opportunity-evidence ${expanded ? "open" : ""}`} aria-hidden={!expanded}><div className="opportunity-evidence-inner">
            <EvidenceRow label="关注逻辑" value={item.thesis} />
            <EvidenceRow label="当前条件" value={item.status} />
            <EvidenceRow label="行情来源" value={providerLabel(item.data_quality.provider)} icon={<Database />} />
            <EvidenceRow label="更新时间" value={item.data_quality.observed_at ? `${relativeTime(item.data_quality.observed_at)} · ${new Date(item.data_quality.observed_at).toLocaleString("zh-CN", { hour12: false })}` : "尚未取得有效行情时间"} />
            <EvidenceRow label="数据说明" value={issues.length ? issues.join("；") : "当前行情可用于机会观察。"} />
        </div></div>
    </article>;
}

function EvidenceRow({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
    return <div className="opportunity-evidence-row"><span>{icon}{label}</span><p>{value}</p></div>;
}

function providerLabel(provider: string) {
    if (provider === "futu_opend") return "富途 OpenD";
    if (provider === "finnhub") return "Finnhub 兜底行情";
    if (provider === "futu_opend+finnhub") return "OpenD 与 Finnhub 联合检查";
    return provider || "行情接口";
}

function MiniTrend({ seed }: { seed: string }) {
    return <div className="mini-trend empty" aria-label={`${seed} 历史行情尚未接通`}><Activity /><span>OpenD 历史 K 线接通后显示 30 / 90 日趋势</span></div>;
}

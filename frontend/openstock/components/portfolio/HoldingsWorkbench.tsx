"use client";

import { useEffect, useState } from "react";
import { CircleAlert, RefreshCw, WalletCards } from "lucide-react";
import { apiFetch, formatMoney, Holding, HoldingsPayload, relativeTime } from "@/lib/decision-api";

const marketNames = { US: "美股", HK: "港股", CN: "A 股" };

export default function HoldingsWorkbench() {
    const [data, setData] = useState<HoldingsPayload | null>(null);
    const [error, setError] = useState("");
    useEffect(() => { void apiFetch<HoldingsPayload>("/api/v1/holdings").then(setData).catch((e) => setError(e.message)); }, []);
    if (!data) return <div className="page-loading">{error ? <><CircleAlert /><strong>{error}</strong></> : <><RefreshCw className="spin" /><strong>正在整理持仓…</strong></>}</div>;

    return <div className="page-stack">
        <section className="page-intro"><div><p className="eyebrow">PORTFOLIO</p><h1>持仓与敞口</h1><p>保留原币账户视角，同时用人民币估算组合规模和主题集中度。</p></div><span className={`snapshot-chip ${data.snapshot.status}`}>{data.snapshot.status === "fresh" ? "账户可用" : "账户待同步"} · {relativeTime(data.snapshot.as_of)}</span></section>
        <section className="portfolio-hero">
            <div className="portfolio-total"><WalletCards /><span>人民币估算总持仓</span><strong>{formatMoney(data.summary.estimated_total_cny)}</strong><small>当前汇率为参考值，不用于生成订单价格</small></div>
            <div className="currency-strip">{Object.entries(data.summary.original_currency_values).map(([currency, value]) => <div key={currency}><span>{currency}</span><strong>{formatMoney(value, currency)}</strong></div>)}</div>
        </section>
        <section className="holdings-layout">
            <div className="holding-groups">{(["US", "HK", "CN"] as const).map((market) => <MarketTable key={market} market={market} holdings={data.holdings.filter((holding) => holding.market === market)} />)}</div>
            <aside className="concentration-panel"><p className="eyebrow">EXPOSURE</p><h2>主题集中度</h2><p className="aside-copy">用于识别组合是否过度押注同一条逻辑。</p><div className="concentration-list">{data.summary.theme_concentration.map((item) => <div key={item.theme}><div><span>{themeName(item.theme)}</span><strong>{item.weight_percent}%</strong></div><i><b style={{ width: `${Math.min(item.weight_percent, 100)}%` }} /></i></div>)}</div></aside>
        </section>
    </div>;
}

function MarketTable({ market, holdings }: { market: "US" | "HK" | "CN"; holdings: Holding[] }) {
    return <section className="market-section"><div className="section-heading compact"><div><span className="market-code">{market}</span><div><h2>{marketNames[market]}</h2><p>{holdings.length} 个持仓</p></div></div></div><div className="holdings-table-wrap"><table className="holdings-table"><thead><tr><th>标的</th><th>数量</th><th>价格 / 来源</th><th>市值</th><th>盈亏</th></tr></thead><tbody>{holdings.map((holding) => {
        const pnl = holding.holding_pnl_percent;
        return <tr key={holding.symbol}><td><strong>{holding.symbol}</strong><span>{holding.name}</span></td><td>{holding.quantity}</td><td><strong>{holding.live_price ?? holding.screenshot_price ?? holding.price ?? "—"}</strong><span className={holding.display_price_source === "live_quote" ? "live-source" : "fallback-source"}>{quoteSourceLabel(holding)}</span></td><td><strong>{formatMoney(holding.live_market_value ?? holding.market_value, holding.currency)}</strong><span>{holding.currency}</span></td><td className={typeof pnl === "number" ? pnl >= 0 ? "positive" : "negative" : ""}><strong>{typeof pnl === "number" ? `${pnl > 0 ? "+" : ""}${pnl.toFixed(2)}%` : "—"}</strong><span>{typeof holding.holding_pnl === "number" ? formatMoney(holding.holding_pnl, holding.currency) : "暂无"}</span></td></tr>;
    })}</tbody></table></div></section>;
}

function quoteSourceLabel(holding: Holding) {
    if (holding.display_price_source !== "live_quote") return "账户快照";
    const session = holding.live_quote?.market_session;
    if (session === "premarket") return "盘前行情";
    if (session === "afterhours") return "盘后行情";
    return "实时行情";
}

function themeName(value: string) { return value.replaceAll("_", " ").replace("ai semiconductor storage", "AI 半导体与存储").replace("ai power building cooling", "AI 电力与冷却").replace("derivative", "衍生品").replace("consumer electronics", "消费电子"); }

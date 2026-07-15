"use client";

import { Check, ChevronDown, RefreshCw, Save, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, RiskConfiguration } from "@/lib/decision-api";

type ProfileDraft = {
    stop_price: string;
    target_weight_percent: string;
    expiry_date: string;
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
};

const emptyProfile = (): ProfileDraft => ({
    stop_price: "", target_weight_percent: "", expiry_date: "", thesis_invalidation: "", thesis_summary: "",
    information_grade: "unrated", research_confidence: "unrated", investment_certainty: "unrated",
    strongest_bear_case: "", buy_add_conditions: "", reduce_conditions: "", exit_invalidation_conditions: "",
    bear_scenario: "", base_scenario: "", bull_scenario: "", position_intent: "long_term", price_response: "review",
});

export default function RiskRulesWorkbench() {
    const [settings, setSettings] = useState<RiskConfiguration | null>(null);
    const [draft, setDraft] = useState<RiskConfiguration | null>(null);
    const [profiles, setProfiles] = useState<Record<string, ProfileDraft>>({});
    const [busy, setBusy] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        void apiFetch<RiskConfiguration>("/api/v1/settings/risk").then((payload) => {
            setSettings(payload); setDraft(payload); setProfiles(profileDrafts(payload));
        }).catch((cause) => setError(cause instanceof Error ? cause.message : "风险规则加载失败"));
    }, []);

    async function save() {
        if (!draft) return;
        setBusy(true); setError("");
        try {
            const activeProfiles = Object.entries(profiles).flatMap(([symbol, profile]) => {
                if (!hasRule(profile)) return [];
                return [{
                    ...profile,
                    symbol,
                    stop_price: profile.stop_price ? Number(profile.stop_price) : null,
                    target_weight_percent: profile.target_weight_percent ? Number(profile.target_weight_percent) : null,
                    expiry_date: profile.expiry_date || null,
                }];
            });
            const payload = await apiFetch<RiskConfiguration>("/api/v1/settings/risk", {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    max_single_position_percent: Number(draft.max_single_position_percent),
                    daily_move_alert_percent: Number(draft.daily_move_alert_percent),
                    warrant_expiry_warning_days: Number(draft.warrant_expiry_warning_days),
                    target_weight_tolerance_percent: Number(draft.target_weight_tolerance_percent), profiles: activeProfiles,
                }),
            });
            setSettings(payload); setDraft(payload); setProfiles(profileDrafts(payload)); setSaved(true);
            window.setTimeout(() => setSaved(false), 2400);
        } catch (cause) { setError(cause instanceof Error ? cause.message : "风险规则保存失败"); }
        finally { setBusy(false); }
    }

    if (!settings || !draft) return <section className="settings-panel risk-settings-panel"><RefreshCw className="spin" /><strong>{error || "正在读取风险规则…"}</strong></section>;

    return <section className="settings-panel risk-settings-panel">
        <div className="settings-panel-heading"><div className="settings-heading-icon"><ShieldAlert /></div><div><h2>组合规则与逐标的论文</h2><p>通用阈值只触发复核；买入、减仓和退出必须满足用户保存的前置条件。</p></div></div>
        <div className="generic-rule-grid">
            <RuleNumber label="单一持仓集中度" suffix="%" value={draft.max_single_position_percent} onChange={(value) => setDraft({ ...draft, max_single_position_percent: value })} detail="只提示风险贡献复核，不是减仓目标" />
            <RuleNumber label="单日异常波动" suffix="%" value={draft.daily_move_alert_percent} onChange={(value) => setDraft({ ...draft, daily_move_alert_percent: value })} detail="先归因公告、行业和资金面" />
            <RuleNumber label="权证到期预警" suffix="天" value={draft.warrant_expiry_warning_days} onChange={(value) => setDraft({ ...draft, warrant_expiry_warning_days: value })} detail="同时检查条款、流动性与价差" />
            <RuleNumber label="目标仓位容忍度" suffix="百分点" value={draft.target_weight_tolerance_percent} onChange={(value) => setDraft({ ...draft, target_weight_tolerance_percent: value })} detail="偏离本身不构成交易理由" />
        </div>

        <div className="holding-rule-heading"><div><SlidersHorizontal /><span><strong>每标的决策档案</strong><small>清仓后自动停用；重新买入不会沿用旧论文</small></span></div><em>{settings.active_profile_count} 组已启用</em></div>
        <div className="holding-rule-list">{draft.holdings.map((holding) => {
            const profile = profiles[holding.symbol] || emptyProfile();
            return <details className="holding-rule-row" key={holding.symbol}>
                <summary><div className="holding-rule-symbol"><strong>{holding.symbol}</strong><span>{holding.name}</span><small>{holding.security_type === "warrant" ? "权证" : holding.market}</small></div><span className={hasRule(profile) ? "profile-state configured" : "profile-state"}>{hasRule(profile) ? "已配置" : "待填写"}</span><ChevronDown /></summary>
                <div className="holding-rule-editor">
                    <div className="profile-select-grid">
                        <SelectField label="持仓意图" value={profile.position_intent} onChange={(value) => updateProfile(holding.symbol, "position_intent", value, setProfiles)} options={{ long_term: "长期投资", tactical: "战术交易", derivative: "衍生品" }} />
                        <SelectField label="信息等级" value={profile.information_grade} onChange={(value) => updateProfile(holding.symbol, "information_grade", value, setProfiles)} options={{ unrated: "未评定", A: "A · 一手正式信息", B: "B · 可核验二手信息", C: "C · 待核验线索" }} />
                        <SelectField label="研究置信度" value={profile.research_confidence} onChange={(value) => updateProfile(holding.symbol, "research_confidence", value, setProfiles)} options={confidenceOptions} />
                        <SelectField label="投资确定性" value={profile.investment_certainty} onChange={(value) => updateProfile(holding.symbol, "investment_certainty", value, setProfiles)} options={confidenceOptions} />
                    </div>
                    <div className="profile-text-grid">
                        <TextField label="投资论文摘要" value={profile.thesis_summary} placeholder="业务、价值获取、持续驱动、错价与失败路径" onChange={(value) => updateProfile(holding.symbol, "thesis_summary", value, setProfiles)} />
                        <TextField label="最强反方" value={profile.strongest_bear_case} placeholder="最有力的反对观点、已计价乐观预期和脆弱假设" onChange={(value) => updateProfile(holding.symbol, "strongest_bear_case", value, setProfiles)} />
                        <TextField label="买入 / 加仓条件" value={profile.buy_add_conditions} placeholder="必须同时满足的论文、价格、数据与敞口条件" onChange={(value) => updateProfile(holding.symbol, "buy_add_conditions", value, setProfiles)} />
                        <TextField label="减仓条件" value={profile.reduce_conditions} placeholder="风险收益恶化、风险贡献或机会成本条件" onChange={(value) => updateProfile(holding.symbol, "reduce_conditions", value, setProfiles)} />
                        <TextField label="退出 / 论文失效条件" value={profile.exit_invalidation_conditions} placeholder="可被证据核验的明确失效条件" onChange={(value) => updateProfile(holding.symbol, "exit_invalidation_conditions", value, setProfiles)} />
                    </div>
                    <div className="scenario-grid">
                        <TextField label="Bear 悲观情景" value={profile.bear_scenario} placeholder="成立条件、估值逻辑与证据" onChange={(value) => updateProfile(holding.symbol, "bear_scenario", value, setProfiles)} />
                        <TextField label="Base 基准情景" value={profile.base_scenario} placeholder="成立条件、估值逻辑与证据" onChange={(value) => updateProfile(holding.symbol, "base_scenario", value, setProfiles)} />
                        <TextField label="Bull 乐观情景" value={profile.bull_scenario} placeholder="成立条件、估值逻辑与证据" onChange={(value) => updateProfile(holding.symbol, "bull_scenario", value, setProfiles)} />
                    </div>
                    <div className="profile-number-grid">
                        <label><span>价格复核线</span><input type="number" min="0" step="any" placeholder="未设置" value={profile.stop_price} onChange={(event) => updateProfile(holding.symbol, "stop_price", event.target.value, setProfiles)} /><small>长期股票默认不执行硬退出</small></label>
                        <SelectField label="触线响应" value={profile.price_response} onChange={(value) => updateProfile(holding.symbol, "price_response", value, setProfiles)} options={{ review: "复核", stop_adding: "暂停加仓", reduce: "减仓检查", exit: "退出（仅战术/衍生品）" }} />
                        <label><span>目标仓位</span><div><input type="number" min="0" max="100" step="0.1" placeholder="未设置" value={profile.target_weight_percent} onChange={(event) => updateProfile(holding.symbol, "target_weight_percent", event.target.value, setProfiles)} /><i>%</i></div><small>还必须填写对应操作条件</small></label>
                        <label><span>到期日</span><input type="date" disabled={!(["warrant", "cbbc"].includes(holding.security_type))} value={profile.expiry_date} onChange={(event) => updateProfile(holding.symbol, "expiry_date", event.target.value, setProfiles)} /><small>仅衍生品使用</small></label>
                    </div>
                </div>
            </details>;
        })}</div>

        <div className="suggestion-policy"><ShieldAlert /><p><strong>模型没有规则修改权</strong><span>动作、数量、风险级别、触发依据、当前限制和失效条件均由确定性代码锁定；模型只可润色标题与摘要。</span></p></div>
        {error && <p className="error-banner">{error}</p>}
        <div className="settings-savebar"><span>{saved ? "决策档案已保存，并已重新检查全部持仓" : `${settings.inactive_profile_count} 组历史规则已停用`}</span><button className="primary-button" type="button" disabled={busy} onClick={save}>{busy ? <RefreshCw className="spin" /> : saved ? <Check /> : <Save />}{busy ? "保存并检查" : saved ? "已保存" : "保存并重新检查"}</button></div>
    </section>;
}

const confidenceOptions = { unrated: "未评定", low: "低", medium: "中", high: "高" };

function RuleNumber({ label, suffix, value, onChange, detail }: { label: string; suffix: string; value: number; onChange: (value: number) => void; detail: string }) {
    return <label className="generic-rule-card"><span>{label}</span><div><input type="number" min="0" step="0.5" value={value} onChange={(event) => onChange(Number(event.target.value))} /><strong>{suffix}</strong></div><small>{detail}</small></label>;
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: Record<string, string>; onChange: (value: string) => void }) {
    return <label><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}>{Object.entries(options).map(([key, copy]) => <option key={key} value={key}>{copy}</option>)}</select></label>;
}

function TextField({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (value: string) => void }) {
    return <label><span>{label}</span><textarea rows={3} maxLength={2000} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function hasRule(profile: ProfileDraft) {
    return Boolean(profile.stop_price || profile.target_weight_percent || profile.expiry_date || [profile.thesis_summary, profile.thesis_invalidation, profile.strongest_bear_case, profile.buy_add_conditions, profile.reduce_conditions, profile.exit_invalidation_conditions, profile.bear_scenario, profile.base_scenario, profile.bull_scenario].some((value) => value.trim()));
}

function profileDrafts(payload: RiskConfiguration) {
    const result: Record<string, ProfileDraft> = {};
    for (const holding of payload.holdings) result[holding.symbol] = emptyProfile();
    for (const profile of payload.profiles) {
        if (profile.status !== "active" || !result[profile.symbol]) continue;
        result[profile.symbol] = { ...emptyProfile(), ...profile, stop_price: profile.stop_price?.toString() || "", target_weight_percent: profile.target_weight_percent?.toString() || "", expiry_date: profile.expiry_date || "" };
    }
    return result;
}

function updateProfile(symbol: string, key: keyof ProfileDraft, value: string, setter: React.Dispatch<React.SetStateAction<Record<string, ProfileDraft>>>) {
    setter((current) => ({ ...current, [symbol]: { ...(current[symbol] || emptyProfile()), [key]: value } }));
}

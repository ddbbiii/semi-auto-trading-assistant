"use client";

import { Check, RefreshCw, Save, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, RiskConfiguration } from "@/lib/decision-api";

type ProfileDraft = {
    stop_price: string;
    target_weight_percent: string;
    expiry_date: string;
    thesis_invalidation: string;
};

const emptyProfile = (): ProfileDraft => ({ stop_price: "", target_weight_percent: "", expiry_date: "", thesis_invalidation: "" });

export default function RiskRulesWorkbench() {
    const [settings, setSettings] = useState<RiskConfiguration | null>(null);
    const [draft, setDraft] = useState<RiskConfiguration | null>(null);
    const [profiles, setProfiles] = useState<Record<string, ProfileDraft>>({});
    const [busy, setBusy] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        void apiFetch<RiskConfiguration>("/api/v1/settings/risk").then((payload) => {
            setSettings(payload);
            setDraft(payload);
            setProfiles(profileDrafts(payload));
        }).catch((cause) => setError(cause instanceof Error ? cause.message : "风险规则加载失败"));
    }, []);

    async function save() {
        if (!draft) return;
        setBusy(true);
        setError("");
        try {
            const activeProfiles = Object.entries(profiles).flatMap(([symbol, profile]) => {
                if (!profile.stop_price && !profile.target_weight_percent && !profile.expiry_date && !profile.thesis_invalidation.trim()) return [];
                return [{
                    symbol,
                    stop_price: profile.stop_price ? Number(profile.stop_price) : null,
                    target_weight_percent: profile.target_weight_percent ? Number(profile.target_weight_percent) : null,
                    expiry_date: profile.expiry_date || null,
                    thesis_invalidation: profile.thesis_invalidation.trim(),
                }];
            });
            const payload = await apiFetch<RiskConfiguration>("/api/v1/settings/risk", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    max_single_position_percent: Number(draft.max_single_position_percent),
                    daily_move_alert_percent: Number(draft.daily_move_alert_percent),
                    warrant_expiry_warning_days: Number(draft.warrant_expiry_warning_days),
                    target_weight_tolerance_percent: Number(draft.target_weight_tolerance_percent),
                    profiles: activeProfiles,
                }),
            });
            setSettings(payload);
            setDraft(payload);
            setProfiles(profileDrafts(payload));
            setSaved(true);
            window.setTimeout(() => setSaved(false), 2400);
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : "风险规则保存失败");
        } finally {
            setBusy(false);
        }
    }

    if (!settings || !draft) return <section className="settings-panel risk-settings-panel"><RefreshCw className="spin" /><strong>{error || "正在读取风险规则…"}</strong></section>;

    return <section className="settings-panel risk-settings-panel">
        <div className="settings-panel-heading"><div className="settings-heading-icon"><ShieldAlert /></div><div><h2>风险规则</h2><p>所有标的共用透明阈值；个股规则只有你保存后才生效，不由模型自动决定。</p></div></div>

        <div className="generic-rule-grid">
            <RuleNumber label="单一持仓集中度" suffix="%" value={draft.max_single_position_percent} onChange={(value) => setDraft({ ...draft, max_single_position_percent: value })} detail="达到后提示复核集中度" />
            <RuleNumber label="单日异常波动" suffix="%" value={draft.daily_move_alert_percent} onChange={(value) => setDraft({ ...draft, daily_move_alert_percent: value })} detail="绝对涨跌幅达到后提醒" />
            <RuleNumber label="权证到期预警" suffix="天" value={draft.warrant_expiry_warning_days} onChange={(value) => setDraft({ ...draft, warrant_expiry_warning_days: value })} detail="需要先填写具体到期日" />
            <RuleNumber label="目标仓位容忍度" suffix="百分点" value={draft.target_weight_tolerance_percent} onChange={(value) => setDraft({ ...draft, target_weight_tolerance_percent: value })} detail="偏离超过后才提示调仓" />
        </div>

        <div className="holding-rule-heading"><div><SlidersHorizontal /><span><strong>每标的用户规则</strong><small>留空即不设置；清仓后自动停用，重新买入不会自行恢复</small></span></div><em>{settings.active_profile_count} 组已启用</em></div>
        <div className="holding-rule-list">{draft.holdings.map((holding) => {
            const profile = profiles[holding.symbol] || emptyProfile();
            return <div className="holding-rule-row" key={holding.symbol}>
                <div className="holding-rule-symbol"><strong>{holding.symbol}</strong><span>{holding.name}</span><small>{holding.security_type === "warrant" ? "权证" : holding.market}</small></div>
                <label><span>风险线</span><input type="number" min="0" step="any" placeholder="未设置" value={profile.stop_price} onChange={(event) => updateProfile(holding.symbol, "stop_price", event.target.value, setProfiles)} /></label>
                <label><span>目标仓位</span><div><input type="number" min="0" max="100" step="0.1" placeholder="未设置" value={profile.target_weight_percent} onChange={(event) => updateProfile(holding.symbol, "target_weight_percent", event.target.value, setProfiles)} /><i>%</i></div></label>
                <label><span>到期日</span><input type="date" disabled={holding.security_type !== "warrant"} value={profile.expiry_date} onChange={(event) => updateProfile(holding.symbol, "expiry_date", event.target.value, setProfiles)} /></label>
                <label className="thesis-rule"><span>投资逻辑失效条件</span><input type="text" maxLength={1000} placeholder="例如：核心业务增速连续两个季度低于预期" value={profile.thesis_invalidation} onChange={(event) => updateProfile(holding.symbol, "thesis_invalidation", event.target.value, setProfiles)} /></label>
            </div>;
        })}</div>

        <div className="suggestion-policy"><ShieldAlert /><p><strong>系统建议不会自动生效</strong><span>未来模型提出风险线或目标仓位时，只会进入待确认区；当前没有待确认建议。</span></p></div>
        {error && <p className="error-banner">{error}</p>}
        <div className="settings-savebar"><span>{saved ? "风险规则已保存，并已重新检查全部持仓" : `${settings.inactive_profile_count} 组历史规则已停用`}</span><button className="primary-button" type="button" disabled={busy} onClick={save}>{busy ? <RefreshCw className="spin" /> : saved ? <Check /> : <Save />}{busy ? "保存并计算" : saved ? "已保存" : "保存并重新计算"}</button></div>
    </section>;
}

function RuleNumber({ label, suffix, value, onChange, detail }: { label: string; suffix: string; value: number; onChange: (value: number) => void; detail: string }) {
    return <label className="generic-rule-card"><span>{label}</span><div><input type="number" min="0" step="0.5" value={value} onChange={(event) => onChange(Number(event.target.value))} /><strong>{suffix}</strong></div><small>{detail}</small></label>;
}

function profileDrafts(payload: RiskConfiguration) {
    const result: Record<string, ProfileDraft> = {};
    for (const holding of payload.holdings) result[holding.symbol] = emptyProfile();
    for (const profile of payload.profiles) {
        if (profile.status !== "active" || !result[profile.symbol]) continue;
        result[profile.symbol] = {
            stop_price: profile.stop_price?.toString() || "",
            target_weight_percent: profile.target_weight_percent?.toString() || "",
            expiry_date: profile.expiry_date || "",
            thesis_invalidation: profile.thesis_invalidation || "",
        };
    }
    return result;
}

function updateProfile(symbol: string, key: keyof ProfileDraft, value: string, setter: React.Dispatch<React.SetStateAction<Record<string, ProfileDraft>>>) {
    setter((current) => ({ ...current, [symbol]: { ...(current[symbol] || emptyProfile()), [key]: value } }));
}

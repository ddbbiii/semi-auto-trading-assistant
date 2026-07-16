"use client";

import {
    AlertTriangle,
    Activity,
    Check,
    Clock3,
    CloudSun,
    MoonStar,
    RefreshCw,
    Save,
    ShieldCheck,
    SunMedium,
} from "lucide-react";
import { useEffect, useState } from "react";
import { AnalysisSettings, apiFetch, LlmStatus, relativeTime, SystemStatus } from "@/lib/decision-api";

type SessionKey = "analyze_us_premarket" | "analyze_regular_session" | "analyze_us_afterhours";

const sessions: Array<{
    key: SessionKey;
    title: string;
    time: string;
    detail: string;
    icon: typeof SunMedium;
}> = [
    {
        key: "analyze_us_premarket",
        title: "美股盘前",
        time: "04:00–09:30 ET",
        detail: "适合检查隔夜消息和开盘前价格变化。",
        icon: CloudSun,
    },
    {
        key: "analyze_regular_session",
        title: "盘中",
        time: "A 股 · 港股 · 美股",
        detail: "覆盖三个市场各自的正常连续交易时段。",
        icon: SunMedium,
    },
    {
        key: "analyze_us_afterhours",
        title: "美股盘后",
        time: "16:00–20:00 ET",
        detail: "适合跟踪财报和盘后重大价格变化。",
        icon: MoonStar,
    },
];

export default function AnalysisSettingsWorkbench() {
    const [settings, setSettings] = useState<AnalysisSettings | null>(null);
    const [draft, setDraft] = useState<AnalysisSettings | null>(null);
    const [hours, setHours] = useState("2");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [saved, setSaved] = useState(false);
    const [model, setModel] = useState<LlmStatus | null>(null);
    const [modelTesting, setModelTesting] = useState(false);
    const [modelError, setModelError] = useState("");

    useEffect(() => {
        void apiFetch<AnalysisSettings>("/api/v1/settings/analysis")
            .then((payload) => {
                setSettings(payload);
                setDraft(payload);
                setHours(String(payload.interval_minutes / 60));
            })
            .catch((cause) => setError(cause instanceof Error ? cause.message : "分析设置加载失败"));
        void apiFetch<SystemStatus>("/api/v1/system/status")
            .then((payload) => setModel(payload.llm ?? null))
            .catch((cause) => setModelError(cause instanceof Error ? cause.message : "模型状态加载失败"));
    }, []);

    async function testModel() {
        setModelTesting(true);
        setModelError("");
        try {
            setModel(await apiFetch<LlmStatus>("/api/v1/system/test-llm", { method: "POST" }));
        } catch (cause) {
            setModelError(cause instanceof Error ? cause.message : "模型 API 测试失败");
        } finally {
            setModelTesting(false);
        }
    }

    async function save() {
        if (!draft) return;
        const parsedHours = Number(hours);
        if (!Number.isFinite(parsedHours) || parsedHours < 0.5 || parsedHours > 24) {
            setError("分析间隔需设置为 0.5 到 24 小时。");
            return;
        }
        setBusy(true);
        setError("");
        setSaved(false);
        try {
            const payload = await apiFetch<AnalysisSettings>("/api/v1/settings/analysis", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    interval_minutes: Math.round(parsedHours * 60),
                    analyze_us_premarket: draft.analyze_us_premarket,
                    analyze_regular_session: draft.analyze_regular_session,
                    analyze_us_afterhours: draft.analyze_us_afterhours,
                }),
            });
            setSettings(payload);
            setDraft(payload);
            setHours(String(payload.interval_minutes / 60));
            setSaved(true);
            window.setTimeout(() => setSaved(false), 2400);
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : "保存失败");
        } finally {
            setBusy(false);
        }
    }

    if (!draft || !settings) {
        return (
            <div className="page-loading">
                {error ? <strong>{error}</strong> : <><RefreshCw className="spin" /><strong>正在读取分析计划…</strong></>}
            </div>
        );
    }

    const dirty =
        Math.round(Number(hours) * 60) !== settings.interval_minutes
        || sessions.some(({ key }) => draft[key] !== settings[key]);
    const currentLabel = settings.enabled_current_sessions.length
        ? settings.enabled_current_sessions.join("、")
        : settings.current_sessions.length
            ? `${settings.current_sessions.join("、")}未启用`
            : "当前休市";

    return (
        <div className="page-stack settings-workbench">
            <section className="page-intro">
                <div>
                    <p className="eyebrow">ANALYSIS SCHEDULE</p>
                    <h1>分析计划</h1>
                    <p>控制完整行情与模型分析的频率。轻量风险监控仍每 15 分钟运行，不消耗模型分析次数。</p>
                </div>
                <span className={`snapshot-chip ${settings.enabled_current_sessions.length ? "fresh" : "stale"}`}>
                    {currentLabel}
                </span>
            </section>

            <div className="settings-layout">
                <section className="settings-panel schedule-editor">
                    <div className="settings-panel-heading">
                        <div className="settings-heading-icon"><Clock3 /></div>
                        <div><h2>完整分析频率</h2><p>进入任一启用市场时段后，按此间隔重新获取行情并生成解释。</p></div>
                    </div>

                    <label className="interval-control">
                        <span>分析间隔</span>
                        <div><input type="number" min="0.5" max="24" step="0.5" value={hours} onChange={(event) => setHours(event.target.value)} /><strong>小时</strong></div>
                        <small>可设置 0.5–24 小时，默认 2 小时；调度器最多延后 5 分钟触发。</small>
                    </label>

                    <div className="session-section">
                        <div><strong>参与分析的交易时段</strong><span>纽约时间会自动处理夏令时</span></div>
                        <div className="session-grid">
                            {sessions.map(({ key, title, time, detail, icon: Icon }) => {
                                const enabled = draft[key];
                                return (
                                    <button
                                        className={`session-card ${enabled ? "enabled" : ""}`}
                                        key={key}
                                        type="button"
                                        aria-pressed={enabled}
                                        onClick={() => setDraft((current) => current ? { ...current, [key]: !current[key] } : current)}
                                    >
                                        <span className="session-card-icon"><Icon /></span>
                                        <span className="session-card-copy"><strong>{title}</strong><small>{time}</small><em>{detail}</em></span>
                                        <span className="session-toggle" aria-hidden="true"><i>{enabled && <Check />}</i></span>
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {error && <p className="error-banner">{error}</p>}
                    <div className="settings-savebar">
                        <span>{dirty ? "有尚未保存的更改" : saved ? "设置已保存并立即生效" : `上次更新：${relativeTime(settings.updated_at)}`}</span>
                        <button className="primary-button" type="button" disabled={busy || !dirty} onClick={save}>
                            {busy ? <RefreshCw className="spin" /> : saved ? <Check /> : <Save />}
                            {busy ? "保存中" : saved ? "已保存" : "保存设置"}
                        </button>
                    </div>
                </section>

                <aside className="schedule-status-panel">
                    <p className="eyebrow">RUNTIME</p>
                    <h2>运行状态</h2>
                    <div className="schedule-runtime-list">
                        <RuntimeItem icon={Activity} label="当前市场" value={settings.current_sessions.join("、") || "全部休市"} />
                        <RuntimeItem icon={ShieldCheck} label="当前是否分析" value={settings.enabled_current_sessions.length ? "已启用" : "不运行完整分析"} tone={settings.enabled_current_sessions.length ? "good" : "quiet"} />
                        <RuntimeItem icon={Clock3} label="上次完整分析" value={settings.last_analysis_at ? relativeTime(settings.last_analysis_at) : "尚未自动运行"} />
                        <RuntimeItem icon={SunMedium} label="下次间隔到期" value={settings.next_due_at ? dueTime(settings.next_due_at) : "进入启用时段后立即"} />
                    </div>
                    <div className="schedule-note"><ShieldCheck /><p><strong>两层刷新互不冲突</strong><span>15 分钟风险监控只运行确定性规则；这里控制的是会调用模型生成解释的完整分析。</span></p></div>
                </aside>
            </div>
            <ModelApiPanel model={model} testing={modelTesting} error={modelError} onTest={() => void testModel()} />
        </div>
    );
}

function ModelApiPanel({ model, testing, error, onTest }: { model: LlmStatus | null; testing: boolean; error: string; onTest: () => void }) {
    const state = !model || model.status === "not_configured" ? "bad" : model.connectivity === "error" ? "bad" : model.connectivity === "ok" ? "good" : "unknown";
    const label = !model ? "读取中" : model.status === "not_configured" ? "未配置" : model.connectivity === "error" ? "调用失败" : model.connectivity === "ok" ? "连接正常" : "尚未测试";
    return <section id="model-api" className="settings-panel model-api-panel">
        <div className="settings-panel-heading"><div className="settings-heading-icon"><AlertTriangle /></div><div><h2>大模型 API</h2><p>模型只负责解释确定性规则，不改变动作、仓位或风险等级。</p></div></div>
        <div className={`model-api-status ${state}`}>
            <span>当前连接状态</span><strong>{label}</strong>
            <small>{error || model?.message || "正在读取模型 API 状态…"}{model?.model ? ` · 模型：${model.model}` : ""}</small>
            <button type="button" disabled={testing} onClick={onTest}>{testing ? "测试中…" : "测试连接"}</button>
        </div>
    </section>;
}

function RuntimeItem({ icon: Icon, label, value, tone = "" }: { icon: typeof Activity; label: string; value: string; tone?: string }) {
    return <div className={`runtime-item ${tone}`}><Icon /><span><small>{label}</small><strong>{value}</strong></span></div>;
}

function dueTime(value: string) {
    const minutes = Math.ceil((new Date(value).getTime() - Date.now()) / 60000);
    if (minutes <= 0) return "已到期，等待启用时段";
    if (minutes < 60) return `约 ${minutes} 分钟后`;
    const hours = Math.round(minutes / 6) / 10;
    return `约 ${hours} 小时后`;
}

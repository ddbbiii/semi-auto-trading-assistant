"use client";

import { BookOpenCheck, RefreshCw, Scale, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, InvestmentPolicy } from "@/lib/decision-api";

export default function InvestmentPolicyWorkbench() {
    const [policy, setPolicy] = useState<InvestmentPolicy | null>(null);
    const [error, setError] = useState("");

    useEffect(() => {
        void apiFetch<InvestmentPolicy>("/api/v1/settings/investment-policy")
            .then(setPolicy)
            .catch((cause) => setError(cause instanceof Error ? cause.message : "投资决策政策加载失败"));
    }, []);

    if (!policy) return <section className="settings-panel policy-settings-panel"><RefreshCw className="spin" /><strong>{error || "正在读取投资决策政策…"}</strong></section>;

    return <section className="settings-panel policy-settings-panel">
        <div className="settings-panel-heading"><div className="settings-heading-icon"><BookOpenCheck /></div><div><h2>{policy.name}</h2><p>版本 {policy.version} · 这是系统生成动作时唯一采用的产品规则，不是模型提示词。</p></div></div>
        <div className="policy-principles">{policy.principles.map((item) => <div key={item}><ShieldCheck /><span>{item}</span></div>)}</div>
        <div className="policy-section-grid">
            <PolicyBlock title="论文与证据等级" items={[
                `论文至少覆盖：${policy.research.thesis.join("、")}`,
                ...Object.entries(policy.research.information_grades).map(([grade, copy]) => `${grade} 级：${copy}`),
                `反方审查：${policy.research.counter_case.join("、")}`,
            ]} />
            <PolicyBlock title="Bear / Base / Bull" items={[policy.scenarios.rule]} />
            <PolicyBlock title="买入与加仓前置条件" items={policy.entry_and_add} />
            <PolicyBlock title="四级响应" items={Object.values(policy.review.responses)} />
            <PolicyBlock title="不同工具的价格线" items={Object.values(policy.instrument_rules)} />
            <PolicyBlock title="有效减仓与退出理由" items={policy.exit_reasons} />
        </div>
        <div className="policy-clean-slate"><Scale /><div><strong>清零测试</strong><span>{policy.review.clean_slate}</span></div></div>
    </section>;
}

function PolicyBlock({ title, items }: { title: string; items: string[] }) {
    return <details className="policy-block"><summary>{title}<span>{items.length} 条</span></summary><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></details>;
}

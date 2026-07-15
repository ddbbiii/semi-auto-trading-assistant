from __future__ import annotations

from typing import Any


POLICY_VERSION = "2026-07-15"


INVESTMENT_DECISION_POLICY: dict[str, Any] = {
    "version": POLICY_VERSION,
    "name": "投资决策框架",
    "principles": [
        "先写清投资论文，再讨论价格和仓位；主题热度本身不是买入依据。",
        "研究置信度与投资确定性分开记录，信息更多不等于赔率更好。",
        "数据不足时允许输出先核验，不强迫给出买入或卖出结论。",
        "确定性代码决定动作、风险级别和数量；模型只能解释，不能改写风控结果。",
    ],
    "research": {
        "thesis": ["业务与价值获取", "护城河方向", "持续驱动", "市场错价", "可信的失败路径"],
        "information_grades": {
            "A": "公司公告、交易所、监管文件、产品正式条款等一手信息",
            "B": "独立市场数据或可信财经媒体等可交叉核验的二手信息",
            "C": "线索、评论或尚未完成交叉核验的信息，只能用于提出问题",
        },
        "counter_case": ["最强反方观点", "乐观预期是否已计价", "可证伪证据", "最脆弱假设"],
    },
    "scenarios": {
        "required": ["bear", "base", "bull"],
        "rule": "每个情景记录成立条件、估值逻辑、结果范围与证据，不制造伪精确数字。",
    },
    "entry_and_add": [
        "投资论文仍有效且风险收益比改善",
        "满足用户确认的买入或加仓条件",
        "行情、持仓、现金与敞口数据足够新鲜",
        "不得仅因低于目标仓位、低于成本或害怕错过而加仓",
    ],
    "review": {
        "clean_slate": "如果今天没有持仓，是否仍愿意以当前价格和信息重新买入？",
        "event_classes": {
            "value_event": "改变企业价值或投资论文的事件",
            "sentiment_liquidity": "主要由情绪、流动性或资金面驱动",
            "mixed": "基本面与资金面共同作用",
            "unexplained": "证据不足，先核验公告、行业和资金面",
        },
        "responses": {
            "review": "复核：收集证据并重做风险收益判断",
            "stop_adding": "暂停加仓：保留持仓但不增加风险暴露",
            "reduce": "减仓检查：确认条件后降低风险暴露",
            "exit": "退出：仅用于论文明确失效、衍生品硬约束或已确认的战术止损",
        },
    },
    "instrument_rules": {
        "long_term": "长期股票的价格线默认触发复核或暂停加仓，不机械清仓。",
        "tactical": "战术交易可使用用户明确确认的价格止损和退出语义。",
        "derivative": "权证和牛熊证同时检查到期、条款、流动性、价差、正股与损失约束。",
    },
    "exit_reasons": [
        "投资论文受损或失效",
        "前瞻风险收益显著恶化",
        "风险贡献或相关敞口过高",
        "存在明显更优的机会成本选择",
        "衍生品时间、条款或流动性约束",
    ],
}


def investment_policy_payload() -> dict[str, Any]:
    """Return the canonical, non-sensitive decision policy used by API and UI."""

    return INVESTMENT_DECISION_POLICY

"""Prompt builders for model-backed options analysis."""

from __future__ import annotations

import json

from quant_platform.options.models import OptionEvaluation


def build_options_ai_prompt(evaluation: OptionEvaluation) -> str:
    payload = evaluation.to_dict()
    return "\n".join(
        [
            "你是 QuantPlatform 的期权策略审查助手。",
            "请基于下面的结构化规则检查结果，帮助用户理解这笔期权交易是否符合其低风险策略。",
            "严格限制：",
            "- 不要给出确定性盈利预测。",
            "- 不要输出自动下单指令。",
            "- 如果违反资金、流动性、财报或风险规则，必须明确说明。",
            "- 输出应包含：结论、主要风险、需要确认的数据、可替代选择。",
            "",
            "结构化输入：",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
    )

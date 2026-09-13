"""阶段4.2 报告 prompt 构建(纯函数, 独立可单测)

防幻觉设计:
- 只把 Java 聚合好的"事实包"喂给模型, 报告中所有数字以事实包为准
- prompt 明令禁止引入事实包之外的数字/类别/案例
- 模型只写文字判断, 输出 schema 中不含任何统计字段
"""
from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = (
    "你是热轧钢带表面质量质检分析专家, 负责依据系统给定的【程序统计事实包】"
    "撰写结构化质检结论。事实包中的图片数、缺陷数、占比、置信度、耗时、严重度"
    "均为系统按检测结果实时计算, 是唯一可信数据源。你不得编造、推算或引用事实包"
    "之外的任何数字、缺陷类别与案例; 你的职责是用专业语言解释这些事实的质量含义并"
    "给出可执行的工艺处置建议。"
)

# 输出格式说明(与 jsonschema 校验一致, 改结构必须同步改 llm_client.NARRATIVE_SCHEMA)
OUTPUT_SPEC = """只输出一个 JSON 对象(禁止 markdown 代码围栏与任何多余文字), 字段如下:
{
  "overall_assessment": "字符串, 本批次总体质量结论, 120-300字, 必须围绕事实包中的缺陷率/框密度/主要缺陷类别展开",
  "severity": "字符串枚举, 只能是 low/medium/high/critical 之一; 原则上必须与事实包 rule_severity 一致, 仅当事实包特征与规则定级明显冲突时才可调整",
  "severity_reason": "字符串, 严重度判定理由, 80-200字, 只能引用事实包中的具体字段(如缺陷率、高危类占比、框密度)",
  "class_analysis": [
    {"class_name": "字符串, 必须是事实包 class_stats 中出现的英文类别标识, 不得新增类别",
     "finding": "字符串, 该类缺陷在本批次的表现解读 50-150字, 结合数量/占比/平均置信度",
     "suggestion": "字符串, 针对该类缺陷的工艺排查与处置建议 50-150字"}
  ],
  "disposition": ["字符串数组, 3-5 条本批次可执行处置建议, 每条 20-80字, 按优先级排序"],
  "risk_summary": "字符串, 放行/返修/报废风险研判与后续抽检建议, 80-200字"
}"""

ANTI_HALLUCINATION_RULES = """严格规则(违反即错误):
1. 事实包之外的数字一律不得出现(不得臆造合格率、吨数、产线编号、历史对比值)
2. class_analysis 只为事实包 class_stats 中存在的类别生成, 顺序按事实包顺序, 不得增删类别
3. disposition 必须针对事实包中真实出现的缺陷类型, 不得给出与钢材表面缺陷无关的泛泛建议
4. 结论要保守: 事实包没体现的信息一律不写; 信息不足时明确写"建议人工复核查验"
5. severity 若与 rule_severity 不一致, severity_reason 必须写明是事实包哪几个字段支撑调整"""


def build_user_prompt(facts: dict[str, Any], class_stats: list[dict[str, Any]]) -> str:
    """组装用户 prompt: 事实包(JSON) + 输出规范 + 防幻觉规则"""
    fact_payload = {
        "batch": facts,
        "class_stats": class_stats,
    }
    facts_json = json.dumps(fact_payload, ensure_ascii=False, indent=2)
    return (
        "以下是本批次的【程序统计事实包】(JSON, 所有数字已由系统校验):\n"
        f"{facts_json}\n\n"
        f"{OUTPUT_SPEC}\n\n"
        f"{ANTI_HALLUCINATION_RULES}\n\n"
        "请基于事实包生成质检报告 JSON:"
    )


def build_repair_prompt(validation_errors: list[str]) -> str:
    """首次输出不符合 schema 时的修复指令(携带原对话由调用方重放)"""
    issues = "\n".join(f"- {e}" for e in validation_errors)
    return (
        "你上次的输出不符合约定的 JSON Schema, 具体问题:\n"
        f"{issues}\n\n"
        "请严格修正上述问题, 仍然只输出一个符合约定的 JSON 对象, "
        "不得输出解释文字或代码围栏。"
    )

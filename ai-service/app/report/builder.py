"""最终报告装配(纯函数): 程序事实块 + 检索证据块 + LLM 叙述块

合并原则(防幻觉落地):
- facts / class_stats / similar_cases 全部原样取程序与检索结果, LLM 碰不到
- 顶层 severity 永远取规则定级; LLM 复核值只存在 narrative.severity,
  两者分歧时 severity_adjusted=True 留痕, 供前端提示"建议人工复核"
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

SCHEMA_VERSION = "1.0"


def build_report(
    batch_facts: dict[str, Any],
    class_stats: list[dict[str, Any]],
    similar_cases: list[dict[str, Any]],
    llm_result: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """装配最终自洽报告 dict(可直接 json.dumps 落 inspect_batch.report_json)"""
    narrative = llm_result["narrative"]
    rule_severity = batch_facts["rule_severity"]
    llm_severity = narrative.get("severity")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
        "model": llm_result["model"],
        "provider": llm_result.get("provider", "dashscope"),
        # 顶层严重度以程序规则为准, LLM 只做语义复核
        "severity": rule_severity,
        "severity_adjusted": llm_severity != rule_severity,
        "facts": batch_facts,
        "class_stats": class_stats,
        "similar_cases": similar_cases,
        "narrative": narrative,
        "tokens": llm_result.get("tokens", {}),
        "latency_ms": llm_result.get("latency_ms", 0.0),
    }

"""报告"相似历史案例"证据块: 本批次代表缺陷 -> Milvus 反查历史库

为什么用代表案例而不是整批统计: 4.1 实测 bbox 裁剪特征 top8 同类率 95.4%,
整图仅 57.1%; 报告证据必须可溯源(每条带裁剪图预签名 URL + 所属历史批次)。

基础设施失败时由路由层兜底为 similar_cases=[], 不阻断报告文字生成。
"""
from __future__ import annotations

from typing import Any

from app.inference.yolo_infer import CLASS_NAME_CN
from app.report.schemas import RepresentativeCase
from app.trace import milvus_client
from app.trace.store import enrich_hits

# 每类取 top2 历史案例, 最多覆盖前 3 大缺陷类 => 证据块上限 6 条
PER_CLASS_TOP_K = 2
MAX_CLASSES = 3
MAX_TOTAL = 6


def find_similar_cases(
    representatives: list[RepresentativeCase],
    exclude_batch_id: int,
) -> list[dict[str, Any]]:
    """用各类别代表案例的入库向量反查历史相似案例(排除本批次自身)"""
    reps = representatives[:MAX_CLASSES]
    if not reps:
        return []

    vectors = milvus_client.query_vectors([r.milvus_pk for r in reps])

    hits: list[dict[str, Any]] = []
    for rep in reps:
        vector = vectors.get(rep.milvus_pk)
        if vector is None:
            continue
        hits.extend(
            milvus_client.search_cases(
                vector,
                top_k=PER_CLASS_TOP_K,
                class_name=rep.class_name,
                exclude_record_id=rep.record_id,
                exclude_batch_id=exclude_batch_id,
            )
        )

    enriched = enrich_hits(hits)
    # 跨类别去重(理论上类别过滤后不会重复, 防御性保序去重) + 总数封顶
    results: list[dict[str, Any]] = []
    seen_case_ids: set[int] = set()
    for item in enriched:
        case_id = item.get("case_id")
        if case_id in seen_case_ids:
            continue
        seen_case_ids.add(case_id)
        item["class_name_cn"] = CLASS_NAME_CN.get(item["class_name"], item["class_name"])
        results.append(item)
        if len(results) >= MAX_TOTAL:
            break
    return results

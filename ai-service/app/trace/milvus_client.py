"""Milvus 缺陷案例向量库客户端

Collection: defect_cases
- pk: VARCHAR 主键 "r{record_id}-{box_index}"(幂等 upsert, 重跑不产生重复)
- vector: 2048 维 FLOAT_VECTOR(已 L2 归一化)
- 标量字段: class_name / record_id / batch_id / confidence / created_at
- 索引: FLAT + COSINE。当前库规模(数千~数万裁剪图)暴力检索毫秒级且召回 100%;
  数据量增长后可平滑换 IVF_FLAT/HNSW(只改建索引参数, 业务侧无感)
- 混合检索: 向量 ANN + class_name 标量过滤(expr), 面试可讲"向量+标量混合过滤"
"""
from __future__ import annotations

import re
import threading
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.config import settings

# 6 类白名单: class_name 过滤条件只允许枚举值, 从根上杜绝表达式注入
ALLOWED_CLASSES: frozenset[str] = frozenset(
    {
        "crazing",
        "inclusion",
        "patches",
        "pitted_surface",
        "rolled-in_scale",
        "scratches",
    }
)

_lock = threading.Lock()
_collection: Collection | None = None


def _connect() -> None:
    """连接 Milvus(已连接则跳过)"""
    connections.connect(
        alias="default",
        host=settings.milvus_host,
        port=settings.milvus_port,
        # 本机 docker, 秒级连接; 失败快速报错便于 Java 侧转 503
        connect_timeout=10,
    )


def _build_schema(dim: int) -> CollectionSchema:
    fields = [
        FieldSchema(
            name="pk",
            dtype=DataType.VARCHAR,
            is_primary=True,
            max_length=128,
        ),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="class_name", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="record_id", dtype=DataType.INT64),
        FieldSchema(name="batch_id", dtype=DataType.INT64),
        FieldSchema(name="confidence", dtype=DataType.FLOAT),
        FieldSchema(name="created_at", dtype=DataType.INT64),
    ]
    return CollectionSchema(
        fields=fields,
        description="SteelGuard 钢材表面缺陷裁剪图特征库(ResNet50-2048d, COSINE)",
        enable_dynamic_field=False,
    )


def get_collection(auto_create: bool = True) -> Collection:
    """获取已 load 的 defect_cases 集合(双重检查锁单例)"""
    global _collection
    if _collection is not None:
        return _collection
    with _lock:
        if _collection is not None:
            return _collection
        _connect()
        name = settings.milvus_collection
        if not utility.has_collection(name):
            if not auto_create:
                raise RuntimeError(f"Milvus collection 不存在: {name}")
            coll = Collection(name, schema=_build_schema(settings.embedding_dim))
            coll.create_index(
                field_name="vector",
                index_params={"index_type": "FLAT", "metric_type": "COSINE"},
            )
            coll.load()
        else:
            coll = Collection(name)
            # 进程重启后单例丢失, 已存在的集合也要显式 load 才能搜
            coll.load()
        _collection = coll
        return coll


def build_pk(record_id: int, box_index: int) -> str:
    return f"r{record_id}-{box_index}"


def upsert_cases(items: list[dict[str, Any]]) -> int:
    """批量 upsert 缺陷案例

    items: [{pk, vector(list[float],2048), class_name, record_id,
             batch_id, confidence, created_at}]
    """
    if not items:
        return 0
    coll = get_collection()
    # 不要每条都 flush: flush 会密封 segment 并触发索引/对象存储写入(秒级开销)。
    # growing segment 对 search/query 立即可见, 批量任务结束时统一 flush 一次即可。
    coll.upsert(data=items)
    return len(items)


def flush() -> None:
    """强制落盘密封(批量入库收尾/重置后调用; 在线单图入库无需调用)"""
    get_collection().flush()


def _build_expr(
    class_name: str | None,
    exclude_record_id: int | None,
    exclude_batch_id: int | None = None,
) -> str | None:
    """拼标量过滤表达式(白名单 + int 强转, 防注入)"""
    clauses: list[str] = []
    if class_name:
        cn = class_name.strip().lower()
        if cn not in ALLOWED_CLASSES:
            raise ValueError(f"非法类别过滤值: {class_name!r}")
        # VARCHAR 字面量用双引号; 值来自白名单无需再转义
        clauses.append(f'class_name == "{cn}"')
    if exclude_record_id is not None:
        rid = int(exclude_record_id)
        clauses.append(f"record_id != {rid}")
    if exclude_batch_id is not None:
        bid = int(exclude_batch_id)
        clauses.append(f"batch_id != {bid}")
    return " and ".join(clauses) if clauses else None


def search_cases(
    vector: list[float],
    top_k: int = 8,
    class_name: str | None = None,
    exclude_record_id: int | None = None,
    exclude_batch_id: int | None = None,
) -> list[dict[str, Any]]:
    """向量相似检索(可叠加类别/本记录/本批次排除的标量过滤)

    返回: [{pk, score(余弦相似度, 越大越像), class_name, record_id,
            batch_id, confidence}]
    """
    coll = get_collection()
    expr = _build_expr(class_name, exclude_record_id, exclude_batch_id)
    top_k = max(1, min(int(top_k), 50))
    hits = coll.search(
        data=[vector],
        anns_field="vector",
        param={"metric_type": "COSINE", "params": {}},
        limit=top_k,
        expr=expr,
        output_fields=["class_name", "record_id", "batch_id", "confidence"],
    )
    results: list[dict[str, Any]] = []
    if hits:
        for hit in hits[0]:
            entity = hit.entity
            results.append(
                {
                    "pk": hit.id,
                    "score": round(float(hit.distance), 4),
                    "class_name": entity.get("class_name"),
                    "record_id": entity.get("record_id"),
                    "batch_id": entity.get("batch_id"),
                    "confidence": round(float(entity.get("confidence") or 0.0), 4),
                }
            )
    return results


def query_vectors(pks: list[str]) -> dict[str, list[float]]:
    """按主键批量取向量(4.2 报告: 用本批次代表案例向量反查历史相似案例)

    pk 格式固定为 r{record_id}-{box_index}(build_pk 产出), 非该格式直接忽略,
    不允许拼进表达式, 杜绝注入。
    """
    coll = get_collection()
    valid = [pk for pk in pks if re.fullmatch(r"r\d+-\d+", pk or "")]
    if not valid:
        return {}
    quoted = ",".join(f'"{pk}"' for pk in valid)
    rows = coll.query(expr=f"pk in [{quoted}]", output_fields=["pk", "vector"])
    return {row["pk"]: row["vector"] for row in rows}


def delete_by_batch(batch_id: int) -> None:
    """按批次删除全部向量(历史库 --reset 重建用)"""
    coll = get_collection()
    result = coll.delete(expr=f"batch_id == {int(batch_id)}")
    coll.flush()
    return result


def total_count() -> int:
    """库内案例总数(COUNT 聚合查询, 比 num_entities 实时性好)"""
    coll = get_collection()
    rows = coll.query(expr='pk != ""', output_fields=["count(*)"])
    return int(rows[0]["count(*)"]) if rows else 0


def count_by_class() -> dict[str, int]:
    """按缺陷类别计数(健康看板/验收用)"""
    coll = get_collection()
    counts: dict[str, int] = {}
    for cn in sorted(ALLOWED_CLASSES):
        rows = coll.query(
            expr=f'class_name == "{cn}"',
            output_fields=["count(*)"],
        )
        counts[cn] = int(rows[0]["count(*)"]) if rows else 0
    return counts

"""缺陷溯源路由

- POST /trace/index  内部接口: 一张图的检测框 -> 裁剪 -> MinIO + embedding + Milvus + MySQL
- POST /trace/search 对外(经 Java JWT 网关): 上传图(可指定框) 以图搜图
- GET  /trace/stats  向量库统计(健康看板)
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.inference.yolo_infer import CLASS_NAME_CN, YOLO_CLASSES, decode_image
from app.trace import milvus_client
from app.trace.embedder import crop_with_pad, embedder
from app.trace.indexing import index_detections
from app.trace.schemas import (
    IndexedCase,
    IndexRequest,
    IndexResponse,
    TraceSearchResponse,
    TraceStats,
)
from app.trace.store import enrich_hits

router = APIRouter(prefix="/trace", tags=["缺陷溯源"])


def _milvus_http_error(exc: Exception) -> HTTPException:
    """Milvus/存储类异常统一转 503, 提示基础设施未就绪"""
    return HTTPException(status_code=503, detail=f"向量库/存储不可用: {exc}")


@router.post("/index", response_model=IndexResponse)
def index_cases(req: IndexRequest) -> IndexResponse:
    """一张检测图的全部缺陷框入库(裁剪图->特征->Milvus/MySQL)

    幂等: pk=r{record_id}-{idx}, 重复执行走 upsert + ON DUPLICATE KEY UPDATE。
    """
    if not req.detections:
        return IndexResponse(record_id=req.record_id, indexed=0, embed_ms=0.0)

    try:
        result = index_detections(
            record_id=req.record_id,
            batch_id=req.batch_id,
            image_bucket=req.image_bucket,
            image_object=req.image_object,
            detections=[d.model_dump(mode="json") for d in req.detections],
        )
    except ValueError as exc:  # 图片解码失败等输入类错误
        raise HTTPException(status_code=400, detail=f"入库失败: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - Milvus/Minio/MySQL/模型类基础设施错误
        raise _milvus_http_error(exc) from exc

    return IndexResponse(
        record_id=req.record_id,
        indexed=result["indexed"],
        embed_ms=result["embed_ms"],
        cases=[IndexedCase(**c) for c in result["cases"]],
    )


@router.post("/search", response_model=TraceSearchResponse)
async def search_cases(
    file: UploadFile = File(..., description="待检索的钢材图片"),
    bbox: str | None = Form(default=None, description='可选, 像素坐标 JSON: {"x1":..,"y1":..,"x2":..,"y2":..}'),
    class_name: str | None = Form(default=None, description="可选类别过滤(6 类英文标识)"),
    top_k: int = Form(default=0, description="返回条数, 0=默认 8"),
    exclude_record_id: int | None = Form(default=None, description="可选, 排除某条检测记录自身"),
) -> TraceSearchResponse:
    """以图搜图: 上传图(可只框选某个缺陷区域)检索历史相似缺陷"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        image = decode_image(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"图片解码失败: {exc}") from exc

    # 解析可选框
    used_bbox = False
    query_bbox = None
    if bbox and bbox.strip():
        try:
            query_bbox = json.loads(bbox)
            required = {"x1", "y1", "x2", "y2"}
            if not required.issubset(query_bbox):
                raise ValueError("bbox 必须含 x1/y1/x2/y2")
            used_bbox = True
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"bbox 参数非法: {exc}") from exc

    if class_name:
        class_name = class_name.strip().lower()
        if class_name not in YOLO_CLASSES:
            raise HTTPException(
                status_code=400,
                detail=f"class_name 必须是 6 类之一: {', '.join(YOLO_CLASSES)}",
            )

    crop = crop_with_pad(image, query_bbox) if used_bbox else image

    started = time.perf_counter()
    try:
        vector = embedder.embed_one(crop)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"特征提取失败: {exc}") from exc
    embed_ms = round((time.perf_counter() - started) * 1000, 2)

    try:
        hits = milvus_client.search_cases(
            vector.tolist(),
            top_k=top_k or settings.search_default_topk,
            class_name=class_name,
            exclude_record_id=exclude_record_id,
        )
        total = milvus_client.total_count()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _milvus_http_error(exc) from exc

    results = enrich_hits(hits)
    # 附中文类别名(前端免维护映射)
    for r in results:
        r["class_name_cn"] = CLASS_NAME_CN.get(r["class_name"], r["class_name"])

    return TraceSearchResponse(
        query_class=class_name,
        used_bbox=used_bbox,
        count=len(results),
        total_cases=total,
        embed_ms=embed_ms,
        results=results,
    )


@router.get("/stats", response_model=TraceStats)
def trace_stats() -> TraceStats:
    """向量库统计(健康检查/看板用); Milvus 不在线返回 503"""
    try:
        total = milvus_client.total_count()
        by_class = milvus_client.count_by_class()
    except Exception as exc:  # noqa: BLE001
        raise _milvus_http_error(exc) from exc
    return TraceStats(
        collection=settings.milvus_collection,
        total_cases=total,
        by_class=by_class,
        embedding_dim=settings.embedding_dim,
        embedder_loaded=embedder.loaded,
        embedder_device=embedder.device,
    )

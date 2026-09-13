"""缺陷案例入库核心逻辑(HTTP 路由与历史库初始化脚本共用)

输入一张图 + 检测框, 完成:
取图 -> 裁剪 -> 上传裁剪图 -> ResNet50 提特征 -> Milvus upsert -> MySQL defect_case
"""
from __future__ import annotations

import time
from typing import Any

from app.config import settings
from app.inference.yolo_infer import YOLO_CLASSES, decode_image
from app.trace import milvus_client
from app.trace.embedder import crop_with_pad, embedder
from app.trace.store import (
    encode_crop_jpeg,
    fetch_image_bytes,
    insert_defect_cases,
    upload_crop,
)


def index_detections(
    record_id: int,
    batch_id: int,
    image_bucket: str,
    image_object: str,
    detections: list[dict[str, Any]],
) -> dict[str, Any]:
    """一图多框入库, 返回 {indexed, embed_ms, cases}

    detections: [{class_name, confidence, bbox:{x1,y1,x2,y2}}, ...](dict 形态)
    类别不在 6 类白名单的框跳过; detections 为空直接返回 0。
    """
    if not detections:
        return {"indexed": 0, "embed_ms": 0.0, "cases": []}

    image = decode_image(fetch_image_bytes(image_bucket, image_object))

    crops: list = []
    kept: list[tuple[int, dict[str, Any], bytes, str]] = []
    for idx, det in enumerate(detections):
        class_name = det.get("class_name")
        bbox = det.get("bbox") or {}
        if class_name not in YOLO_CLASSES:
            continue
        crop = crop_with_pad(image, bbox)
        crop_jpeg = encode_crop_jpeg(crop)
        object_key = f"{settings.crop_prefix}/{batch_id}/{record_id}-{idx}.jpg"
        crops.append(crop)
        kept.append((idx, det, crop_jpeg, object_key))

    if not kept:
        return {"indexed": 0, "embed_ms": 0.0, "cases": []}

    started = time.perf_counter()
    vectors = embedder.embed_crops(crops)
    embed_ms = round((time.perf_counter() - started) * 1000, 2)

    now = int(time.time())
    vector_items: list[dict[str, Any]] = []
    db_rows: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    for (idx, det, crop_jpeg, object_key), vector in zip(kept, vectors):
        pk = milvus_client.build_pk(record_id, idx)
        upload_crop(crop_jpeg, object_key)
        conf = float(det.get("confidence", 0.0))
        vector_items.append(
            {
                "pk": pk,
                "vector": vector.tolist(),
                "class_name": det["class_name"],
                "record_id": record_id,
                "batch_id": batch_id,
                "confidence": conf,
                "created_at": now,
            }
        )
        db_rows.append(
            {
                "record_id": record_id,
                "batch_id": batch_id,
                "class_name": det["class_name"],
                "confidence": conf,
                "x1": bbox.get("x1"),
                "y1": bbox.get("y1"),
                "x2": bbox.get("x2"),
                "y2": bbox.get("y2"),
                "crop_minio_path": object_key,
                "milvus_pk": pk,
            }
        )
        cases.append(
            {
                "milvus_pk": pk,
                "class_name": det["class_name"],
                "confidence": round(conf, 4),
                "crop_minio_path": object_key,
            }
        )

    milvus_client.upsert_cases(vector_items)
    insert_defect_cases(db_rows)
    return {"indexed": len(cases), "embed_ms": embed_ms, "cases": cases}

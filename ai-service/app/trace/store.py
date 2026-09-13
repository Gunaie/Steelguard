"""溯源存储层: MinIO(原图读取/裁剪图上传) + MySQL(defect_case 关系镜像)

职责边界:
- Python 写 defect_case(感知结果的附属数据, 与向量同事务语义批量写入)
- Java 负责 inspect_batch/inspect_record 业务主表; 本模块只 JOIN 读取做结果拼装
- Milvus 给相似度/pk, MySQL 给裁剪图路径/批次归属, MinIO 预签名给前端展示
"""
from __future__ import annotations

import io
from typing import Any

import cv2

from app.config import settings
from app.dataset.db import get_connection
from app.dataset.minio_client import get_minio_client, get_presign_client, presigned_url

_minio = None
_presign = None


def get_minio():
    """MinIO 客户端单例(全服务复用一个连接池)"""
    global _minio
    if _minio is None:
        _minio = get_minio_client()
    return _minio


def get_presign():
    """预签名专用客户端单例(对外端点, 只做离线签名)"""
    global _presign
    if _presign is None:
        _presign = get_presign_client()
    return _presign


def fetch_image_bytes(bucket: str, object_path: str) -> bytes:
    """从 MinIO 读取原图字节"""
    client = get_minio()
    resp = None
    try:
        resp = client.get_object(bucket, object_path)
        data = resp.read()
    finally:
        if resp is not None:
            resp.close()
            resp.release_conn()
    if not data:
        raise RuntimeError(f"MinIO 对象为空: {bucket}/{object_path}")
    return data


def encode_crop_jpeg(crop_bgr, quality: int = 95) -> bytes:
    """裁剪图 BGR ndarray -> JPEG 字节(纯编码, 便于单测)"""
    ok, buf = cv2.imencode(".jpg", crop_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("裁剪图 JPEG 编码失败")
    return buf.tobytes()


def upload_crop(crop_jpeg: bytes, object_key: str) -> str:
    """上传裁剪图到 defect-images/crops/..., 返回对象路径"""
    client = get_minio()
    client.put_object(
        bucket_name=settings.defect_bucket,
        object_name=object_key,
        data=io.BytesIO(crop_jpeg),
        length=len(crop_jpeg),
        content_type="image/jpeg",
    )
    return object_key


def insert_defect_cases(rows: list[dict[str, Any]]) -> int:
    """批量写 defect_case(与 Milvus upsert 同一批 pk, 可安全重跑)

    rows: [{record_id, batch_id, class_name, confidence,
            x1,y1,x2,y2, crop_minio_path, milvus_pk}]
    """
    if not rows:
        return 0
    sql = """INSERT INTO defect_case
               (record_id, batch_id, class_name, confidence,
                x1, y1, x2, y2, crop_minio_path, milvus_pk)
             VALUES (%(record_id)s, %(batch_id)s, %(class_name)s, %(confidence)s,
                     %(x1)s, %(y1)s, %(x2)s, %(y2)s, %(crop_minio_path)s, %(milvus_pk)s)
             ON DUPLICATE KEY UPDATE
               confidence=VALUES(confidence),
               x1=VALUES(x1), y1=VALUES(y1), x2=VALUES(x2), y2=VALUES(y2),
               crop_minio_path=VALUES(crop_minio_path)"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def enrich_hits(hits: list[dict[str, Any]], url_expires: int = 3600) -> list[dict[str, Any]]:
    """Milvus 命中结果 -> 带业务元数据与预签名 URL 的展示结构

    - 按 milvus_pk 一次 JOIN 回查, 保持入参 hits 的顺序
    - 查不到关系行的 pk(理论上不应出现) 被丢弃
    """
    if not hits:
        return []
    pks = [h["pk"] for h in hits]
    placeholders = ",".join(["%s"] * len(pks))
    sql = f"""
        SELECT dc.milvus_pk, dc.id AS case_id, dc.record_id, dc.batch_id,
               dc.class_name, dc.confidence, dc.crop_minio_path,
               ir.image_name, ir.minio_bucket AS image_bucket,
               ir.minio_path AS image_minio_path,
               ib.batch_no, ib.name AS batch_name
        FROM defect_case dc
        JOIN inspect_record ir ON ir.id = dc.record_id
        JOIN inspect_batch  ib ON ib.id = dc.batch_id
        WHERE dc.milvus_pk IN ({placeholders})"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, pks)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()

    by_pk = {r["milvus_pk"]: r for r in rows}
    # 预签名 URL 给浏览器使用, 必须走对外端点客户端
    client = get_presign()
    enriched: list[dict[str, Any]] = []
    for hit in hits:
        row = by_pk.get(hit["pk"])
        if row is None:
            continue
        crop_url = presigned_url(client, settings.defect_bucket, row["crop_minio_path"], url_expires)
        source_url = None
        if row.get("image_minio_path"):
            source_url = presigned_url(
                client, row["image_bucket"] or settings.defect_bucket,
                row["image_minio_path"], url_expires,
            )
        enriched.append(
            {
                "case_id": row["case_id"],
                "milvus_pk": hit["pk"],
                "score": hit["score"],
                "class_name": row["class_name"],
                "detect_confidence": round(float(row["confidence"]), 4),
                "record_id": row["record_id"],
                "batch_id": row["batch_id"],
                "batch_no": row["batch_no"],
                "batch_name": row["batch_name"],
                "image_name": row["image_name"],
                "crop_url": crop_url,
                "source_image_url": source_url,
            }
        )
    return enriched

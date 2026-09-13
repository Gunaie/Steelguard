"""里程碑4.1: 历史缺陷案例库初始化

把 NEU-DET v1-raw 1800 张原图全部过 YOLO, 检测框裁剪后入 Milvus + defect_case,
并建立一个 source=history 的质检批次(inspect_batch/inspect_record),
作为"以图搜图"的历史案例底座(后续新批次上传图即可搜到这些历史相似缺陷)。

幂等/重建:
  --reset 会删除既有 HIST-NEUDET-RAW 批次的 MySQL 行 + Milvus 向量 + MinIO 裁剪图后重建
  不带 --reset 且批次已存在则直接退出(防重复入库)

用法(在 ai-service/ 下):
  .\\.venv\\Scripts\\python.exe -u scripts/index_history_cases.py --reset
  .\\.venv\\Scripts\\python.exe -u scripts/index_history_cases.py --limit 50   # 冒烟
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minio.deleteobjects import DeleteObject  # noqa: E402

from app.config import settings  # noqa: E402
from app.dataset.db import get_connection  # noqa: E402
from app.inference.yolo_infer import get_inferencer  # noqa: E402
from app.trace import milvus_client  # noqa: E402
from app.trace.embedder import embedder  # noqa: E402
from app.trace.indexing import index_detections  # noqa: E402
from app.trace.store import get_minio  # noqa: E402

HIST_BATCH_NO = "HIST-NEUDET-RAW"
HIST_NAME = "NEU-DET 历史基线库(1800 张原图)"
HIGH_RISK = {"crazing", "scratches"}


def judge_severity(n: int, defect_images: int, defects: int, high_risk: int) -> str:
    """与 Java SeverityRules 保持一致的定级规则(历史库收尾用)"""
    if n <= 0 or defects == 0:
        return "low"
    rate = defect_images / n
    density = defects / n
    hr = high_risk / defects
    if density >= 3.0 or (rate >= 0.8 and hr >= 0.4):
        return "critical"
    if density >= 1.5 or rate >= 0.5:
        return "high"
    if density >= 0.5 or rate >= 0.2:
        return "medium"
    return "low"


def find_raw_version_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM dataset_version WHERE version='v1-raw' LIMIT 1")
        row = cur.fetchone()
    if not row:
        raise RuntimeError("dataset_version 中找不到 v1-raw, 请先完成阶段1数据导入")
    return int(row[0])


def list_history_batch_ids(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM inspect_batch WHERE batch_no=%s AND deleted=0",
            (HIST_BATCH_NO,),
        )
        return [int(r[0]) for r in cur.fetchall()]


def reset_history(conn, batch_ids: list[int]) -> None:
    """删 Milvus 向量 + MinIO 裁剪图 + MySQL 行"""
    minio_client = get_minio()
    for bid in batch_ids:
        print(f"[reset] 清理历史批次 id={bid}")
        try:
            milvus_client.delete_by_batch(bid)
        except Exception as exc:  # noqa: BLE001
            print(f"[reset] Milvus 删除失败(可能 collection 尚未建): {exc}")
        # MinIO 裁剪图
        prefix = f"{settings.crop_prefix}/{bid}/"
        objs = list(
            minio_client.list_objects(settings.defect_bucket, prefix=prefix, recursive=True)
        )
        if objs:
            errors = minio_client.remove_objects(
                settings.defect_bucket,
                (DeleteObject(o.object_name) for o in objs),
            )
            for err in errors:
                print(f"[reset] MinIO 删除错误: {err}")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM defect_case WHERE batch_id=%s", (bid,))
            cur.execute("DELETE FROM inspect_record WHERE batch_id=%s", (bid,))
            cur.execute("DELETE FROM inspect_batch WHERE id=%s", (bid,))
        conn.commit()


def create_batch(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO inspect_batch
                 (batch_no, name, source, status, image_count, processed_count,
                  defect_image_count, defect_count, case_count, total_inference_ms, reported)
               VALUES (%s, %s, 'history', 'detecting', 0, 0, 0, 0, 0, 0, 0)""",
            (HIST_BATCH_NO, HIST_NAME),
        )
        cur.execute("SELECT LAST_INSERT_ID()")
        bid = int(cur.fetchone()[0])
    conn.commit()
    return bid


def finish_batch(conn, bid: int, total: int, defect_images: int, defects: int,
                 cases: int, high_risk: int, infer_ms: float) -> None:
    severity = judge_severity(total, defect_images, defects, high_risk)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE inspect_batch SET
                 status='done', image_count=%s, processed_count=%s,
                 defect_image_count=%s, defect_count=%s, case_count=%s,
                 severity=%s, total_inference_ms=%s, model=%s, error_msg=NULL
               WHERE id=%s""",
            (total, total, defect_images, defects, cases, severity,
             round(infer_ms, 2), settings.yolo_model_name, bid),
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清空既有历史批次后重建")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 张(0=全部 1800)")
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()

    conn = get_connection()
    version_id = find_raw_version_id(conn)

    existing = list_history_batch_ids(conn)
    if existing and not args.reset:
        print(f"历史批次 {HIST_BATCH_NO} 已存在(id={existing}), 如需重建请加 --reset")
        return
    if existing and args.reset:
        reset_history(conn, existing)

    with conn.cursor() as cur:
        limit_sql = f" LIMIT {int(args.limit)}" if args.limit > 0 else ""
        cur.execute(
            f"""SELECT id, file_name, width, height, minio_path
                FROM dataset_image
                WHERE version_id=%s AND split='raw' AND deleted=0
                ORDER BY id{limit_sql}""",
            (version_id,),
        )
        images = cur.fetchall()
    if not images:
        raise RuntimeError("v1-raw 没有可用图片")

    bid = create_batch(conn)
    print(f"创建历史批次 id={bid} no={HIST_BATCH_NO}, 待入库 {len(images)} 张")

    # 预加载两个模型(GPU YOLO + CPU/GPU ResNet50)
    inferencer = get_inferencer()
    inferencer.load()
    embedder.load()
    print(f"模型就绪: YOLO device={inferencer.device}, Embedder device={embedder.device}")

    minio_client = get_minio()
    t_start = time.perf_counter()

    defect_images = 0
    defect_total = 0
    case_total = 0
    high_risk = 0
    infer_ms_total = 0.0

    for i, (img_id, file_name, width, height, minio_path) in enumerate(images, start=1):
        # 1. 取图 + YOLO
        resp = None
        try:
            obj = minio_client.get_object(settings.minio_bucket, minio_path)
            image_bytes = obj.read()
            obj.close()
            obj.release_conn()
            pred = inferencer.predict(image_bytes, conf=args.conf, iou=0.7)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(images)}] {file_name} 检测失败: {exc}")
            continue

        dets = pred["detections"]
        infer_ms_total += float(pred["inference_ms"])

        # 2. 写 inspect_record
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO inspect_record
                     (batch_id, image_name, width, height, minio_bucket, minio_path,
                      model, inference_ms, det_count, result_json, source_ref)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (bid, file_name, pred["image_width"], pred["image_height"],
                 settings.minio_bucket, minio_path, pred["model"],
                 pred["inference_ms"], pred["count"],
                 json.dumps(dets, ensure_ascii=False), str(img_id)),
            )
            cur.execute("SELECT LAST_INSERT_ID()")
            record_id = int(cur.fetchone()[0])
        conn.commit()

        # 3. 检测框入向量库
        indexed = 0
        if dets:
            try:
                result = index_detections(
                    record_id=record_id,
                    batch_id=bid,
                    image_bucket=settings.minio_bucket,
                    image_object=minio_path,
                    detections=dets,
                )
                indexed = result["indexed"]
            except Exception as exc:  # noqa: BLE001
                print(f"[{i}/{len(images)}] {file_name} 向量入库失败: {exc}")

        if dets:
            defect_images += 1
            defect_total += len(dets)
            high_risk += sum(1 for d in dets if d["class_name"] in HIGH_RISK)
        case_total += indexed

        if i % 25 == 0 or i == len(images):
            elapsed = time.perf_counter() - t_start
            print(
                f"[{i}/{len(images)}] 缺陷图 {defect_images} 框 {defect_total} "
                f"案例 {case_total} 用时 {elapsed:.0f}s",
                flush=True,
            )
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE inspect_batch SET image_count=%s, processed_count=%s,
                         defect_image_count=%s, defect_count=%s, case_count=%s
                       WHERE id=%s""",
                    (i, i, defect_images, defect_total, case_total, bid),
                )
            conn.commit()

    total = len(images)
    finish_batch(conn, bid, total, defect_images, defect_total, case_total,
                 high_risk, infer_ms_total)
    conn.close()

    # 批量入库结束统一 flush 一次, 密封段落盘(避免每条 upsert 都 flush 的秒级开销)
    try:
        milvus_client.flush()
    except Exception as exc:  # noqa: BLE001
        print(f"Milvus flush 警告(数据仍在 growing 段可检索): {exc}")

    elapsed = time.perf_counter() - t_start
    print("=" * 60)
    print(f"历史案例库完成 ✓ 批次 id={bid}")
    print(f"  图片 {total} / 缺陷图 {defect_images} / 缺陷框 {defect_total} / 入库案例 {case_total}")
    print(f"  高危类(裂纹+划痕)框 {high_risk}")
    print(f"  YOLO 纯推理 {infer_ms_total/1000:.1f}s, 总耗时 {elapsed:.0f}s")
    try:
        print(f"  Milvus 库内总数: {milvus_client.total_count()}")
        print(f"  分类计数: {milvus_client.count_by_class()}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Milvus 统计查询失败: {exc}")


if __name__ == "__main__":
    main()

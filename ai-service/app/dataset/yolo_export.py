"""YOLO 格式数据集导出（阶段 2）

把 v1-raw(1800 图/VOC 框) 导出为 ultralytics YOLO 检测格式:

    neu-det-yolo/
    ├── data.yaml                 # 不写 path, 路径相对 yaml 所在目录, 跨机器可移植
    ├── images/{train,val}/       # 图片(200×200 灰度 jpg, YOLO 内部自动转 3 通道)
    ├── labels/{train,val}/       # 每行 "cls_id cx cy w h"(均归一化到 0~1)
    └── splits.txt               # 记录每个原图 stem 的 train/val 归属(复现用)

划分策略:
- 按"图片主类"(首框类, 与文件名前缀 100% 一致)分层 8:2, seed=42 可复现
- 默认 --with-augmented: 训练集每张原图附带 v1-aug5 的 4 张增强图(从 MinIO
  下载, 标签读 MySQL); **val 只保留原图**, 防止增强副本跨集合泄漏
- --raw-only: 只导出 1800 原图(让 ultralytics 在线增强)
"""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import pymysql
import yaml

from app.config import settings
from app.dataset import db
from app.dataset.minio_client import get_minio_client
from app.dataset.voc_parser import VOCDocument, find_voc_files, parse_voc

# 固定顺序(字母序), 训练/推理两端必须一致
YOLO_CLASSES: list[str] = [
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
]
CLASS_TO_ID = {name: idx for idx, name in enumerate(YOLO_CLASSES)}

VAL_RATIO = 0.2
SPLIT_SEED = 42


def voc_bbox_to_yolo(
    xmin: int,
    ymin: int,
    xmax: int,
    ymax: int,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    """PascalVOC 绝对像素坐标 -> YOLO 归一化中心点格式

    Returns:
        (cx, cy, w, h), 理论范围 0~1; 调用方负责最终 clamp
    """
    cx = (xmin + xmax) / 2.0 / width
    cy = (ymin + ymax) / 2.0 / height
    w = (xmax - xmin) / width
    h = (ymax - ymin) / height
    return cx, cy, w, h


def _dedupe_lines(lines: list[str]) -> list[str]:
    """去除完全重复的标签行(保序)

    NEU-DET 源数据有 3 个 xml(crazing_120/inclusion_62/patches_198)
    本身含坐标完全相同的重复框, ultralytics 加载时虽会自动去重,
    导出产物直接去重更干净。
    """
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            result.append(line)
    return result


def write_yolo_label(
    label_path: Path,
    doc: VOCDocument,
) -> int:
    """把 VOCDocument 的全部框写成一个 YOLO txt 标签文件, 返回框数"""
    lines: list[str] = []
    for obj in doc.objects:
        cls_id = CLASS_TO_ID[obj.class_name]
        cx, cy, w, h = voc_bbox_to_yolo(
            obj.xmin, obj.ymin, obj.xmax, obj.ymax, doc.width, doc.height
        )
        # 归一化值钳制到 [0,1], 并过滤退化框
        cx = min(1.0, max(0.0, cx))
        cy = min(1.0, max(0.0, cy))
        w = min(1.0, max(0.0, w))
        h = min(1.0, max(0.0, h))
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    lines = _dedupe_lines(lines)
    label_path.write_text("\n".join(lines), encoding="utf-8")
    return len(lines)


def stratified_split(
    pairs: list[tuple[Path, Path]],
    val_ratio: float = VAL_RATIO,
    seed: int = SPLIT_SEED,
) -> dict[str, set[str]]:
    """按图片主类分层抽样划分 train/val, 返回 {"train": {stems}, "val": {stems}}"""
    by_class: dict[str, list[str]] = {}
    for _, xml_path in pairs:
        doc = parse_voc(xml_path)
        by_class.setdefault(doc.class_name, []).append(xml_path.stem)

    rng = random.Random(seed)
    split: dict[str, set[str]] = {"train": set(), "val": set()}
    for class_name in sorted(by_class):
        stems = sorted(by_class[class_name])
        rng.shuffle(stems)
        n_val = round(len(stems) * val_ratio)
        split["val"].update(stems[:n_val])
        split["train"].update(stems[n_val:])
    return split


def _version_id_by_name(conn, version_name: str) -> int:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "SELECT id FROM dataset_version WHERE version=%s AND status='ready'",
            (version_name,),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"未找到 ready 状态的版本 {version_name}")
    return row["id"]


def _write_data_yaml(out_dir: Path) -> None:
    """写 data.yaml; 不写 path 键, train/val 相对 yaml 父目录, 拷到任何机器都能用"""
    data = {
        "train": "images/train",
        "val": "images/val",
        "nc": len(YOLO_CLASSES),
        "names": YOLO_CLASSES,
    }
    with (out_dir / "data.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def export_yolo_dataset(
    out_dir: Path,
    with_augmented: bool = True,
) -> dict:
    """导出 YOLO 数据集

    Args:
        out_dir: 输出目录(如 data/yolo/neu-det-yolo)
        with_augmented: True=训练集含 v1-aug5 增强图; False=仅 1800 原图

    Returns:
        统计字典(train_images/val_images/train_boxes/val_boxes)
    """
    # 清理旧目录, 保证可重复执行
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    # 定位原图目录(相对 CWD 找不到时回退项目根, 与 importer/augment 同策略)
    project_root = Path(settings.dataset_root)
    if not project_root.is_absolute() and not project_root.exists():
        project_root = Path(__file__).resolve().parents[3] / settings.dataset_root
    project_root = project_root.resolve()
    images_dir = project_root / settings.dataset_images_dir
    annotations_dir = project_root / settings.dataset_annotations_dir

    pairs = find_voc_files(images_dir, annotations_dir)
    print(f"[YOLOExport] 扫描到 {len(pairs)} 对原图/VOC 标注")

    split = stratified_split(pairs)
    print(f"[YOLOExport] 分层划分(seed={SPLIT_SEED}): "
          f"train={len(split['train'])} val={len(split['val'])}")

    stats = {"train_images": 0, "val_images": 0, "train_boxes": 0, "val_boxes": 0}

    # 1) 导出原图
    for img_path, xml_path in pairs:
        part = "val" if xml_path.stem in split["val"] else "train"
        shutil.copy2(img_path, out_dir / f"images/{part}/{img_path.name}")
        doc = parse_voc(xml_path)
        n = write_yolo_label(out_dir / f"labels/{part}/{xml_path.stem}.txt", doc)
        stats[f"{part}_images"] += 1
        stats[f"{part}_boxes"] += n

    # 记录划分(复现用)
    with (out_dir / "splits.txt").open("w", encoding="utf-8") as f:
        for stem in sorted(split["val"]):
            f.write(f"val\t{stem}\n")
        for stem in sorted(split["train"]):
            f.write(f"train\t{stem}\n")

    # 2) 训练集追加增强图(MinIO 图片 + MySQL 标注), val 不动
    if with_augmented:
        conn = db.get_connection()
        try:
            raw_vid = _version_id_by_name(conn, "v1-raw")
            aug_vid = _version_id_by_name(conn, "v1-aug5")
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                # 只取训练集原图(source 原图文件名 stem 在 train 集合内)的增强副本
                cur.execute(
                    """SELECT i.id, i.file_name, i.minio_path, r.file_name AS raw_file_name
                       FROM dataset_image i
                       JOIN dataset_image r ON i.source_image_id = r.id
                       WHERE i.version_id=%s AND i.split='augmented' AND i.deleted=0
                         AND r.version_id=%s AND r.deleted=0
                       ORDER BY i.id""",
                    (aug_vid, raw_vid),
                )
                aug_rows = cur.fetchall()
            aug_rows = [
                r for r in aug_rows
                if Path(r["raw_file_name"]).stem in split["train"]
            ]
            print(f"[YOLOExport] 训练集增强图: {len(aug_rows)} 张, 从 MinIO 下载...")

            client = get_minio_client()
            for idx, row in enumerate(aug_rows, 1):
                img_out = out_dir / "images/train" / row["file_name"]
                client.fget_object(settings.minio_bucket, row["minio_path"], str(img_out))

                with conn.cursor(pymysql.cursors.DictCursor) as cur:
                    cur.execute(
                        "SELECT a.class_name, a.xmin, a.ymin, a.xmax, a.ymax, "
                        "i.width, i.height "
                        "FROM dataset_annotation a "
                        "JOIN dataset_image i ON a.image_id=i.id "
                        "WHERE a.image_id=%s ORDER BY a.id",
                        (row["id"],),
                    )
                    anns = cur.fetchall()

                lines = []
                w = h = 200
                for a in anns:
                    w, h = a["width"], a["height"]
                    cx, cy, bw, bh = voc_bbox_to_yolo(
                        a["xmin"], a["ymin"], a["xmax"], a["ymax"], w, h
                    )
                    cx = min(1.0, max(0.0, cx))
                    cy = min(1.0, max(0.0, cy))
                    bw = min(1.0, max(0.0, bw))
                    bh = min(1.0, max(0.0, bh))
                    if bw > 0 and bh > 0:
                        lines.append(
                            f"{CLASS_TO_ID[a['class_name']]} "
                            f"{cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
                        )
                label_out = out_dir / "labels/train" / f"{Path(row['file_name']).stem}.txt"
                lines = _dedupe_lines(lines)
                label_out.write_text("\n".join(lines), encoding="utf-8")
                stats["train_images"] += 1
                stats["train_boxes"] += len(lines)

                if idx % 500 == 0:
                    print(f"[YOLOExport] 增强图进度 {idx}/{len(aug_rows)}")
        finally:
            conn.close()

    _write_data_yaml(out_dir)
    print(f"[YOLOExport] 完成: {stats}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 YOLO 格式 NEU-DET 数据集")
    parser.add_argument(
        "--out",
        default="data/yolo/neu-det-yolo",
        help="输出目录(默认 data/yolo/neu-det-yolo)",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="仅导出 1800 原图(不含 v1-aug5 增强图)",
    )
    args = parser.parse_args()
    export_yolo_dataset(Path(args.out), with_augmented=not args.raw_only)


if __name__ == "__main__":
    main()

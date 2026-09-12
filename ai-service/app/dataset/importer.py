"""数据集导入器: 批量导入原始 1800 张图到 MinIO + 写 MySQL 元数据

流程:
1. 扫描 IMAGES + ANNOTATIONS 配对
2. 先跑 EDA 校验数据完整性
3. 创建 dataset_version 记录(v1-raw)
4. 逐张: 解析VOC → 上传MinIO → 写dataset_image + dataset_annotation
5. 更新版本状态为 ready
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from app.config import settings
from app.dataset import db
from app.dataset.eda import EDAReport, run_eda
from app.dataset.minio_client import ensure_bucket, get_minio_client, upload_file
from app.dataset.voc_parser import find_voc_files, parse_voc


def import_raw_dataset(
    images_dir: str | Path | None = None,
    annotations_dir: str | Path | None = None,
    version: str = "v1-raw",
    batch_commit: int = 100,
) -> tuple[int, EDAReport]:
    """导入原始数据集到 MinIO + MySQL

    Args:
        images_dir: 图片目录(默认读 settings)
        annotations_dir: 标注目录
        version: 版本号
        batch_commit: 每多少张提交一次

    Returns:
        (version_id, EDAReport)
    """
    # 解析路径: 相对路径优先相对 CWD, 不存在时回退到项目根目录(ai-service 的上级)
    project_root = Path(settings.dataset_root)
    if not project_root.is_absolute() and not project_root.exists():
        project_root = Path(__file__).resolve().parents[3] / settings.dataset_root
    project_root = project_root.resolve()

    images_dir = Path(images_dir) if images_dir else project_root / settings.dataset_images_dir
    annotations_dir = Path(annotations_dir) if annotations_dir else project_root / settings.dataset_annotations_dir

    print(f"[Importer] 图片目录: {images_dir}")
    print(f"[Importer] 标注目录: {annotations_dir}")

    # 1. 扫描配对
    pairs = find_voc_files(images_dir, annotations_dir)
    print(f"[Importer] 配对 {len(pairs)} 张图片-标注")

    # 2. 跑 EDA(同时校验所有标注可解析)
    report = run_eda(images_dir, annotations_dir)
    print(f"[Importer] EDA 完成: {report.total_images} 图 {report.total_annotations} 框")

    # 3. MinIO
    minio_client = get_minio_client()
    ensure_bucket(minio_client, settings.minio_bucket)

    # 4. MySQL: 创建版本
    conn = db.get_connection()
    try:
        version_id = db.create_version(
            conn,
            version=version,
            dataset_name="NEU-DET",
            source="NEU(Northeastern University) via GitHub mirror",
            image_count=report.total_images,
            annotation_count=report.total_annotations,
            augment_factor=1,
            total_count=report.total_images,
            status="importing",
            remark="原始 1800 张, 6 类各 300",
        )
        print(f"[Importer] 版本 {version} -> version_id={version_id}")

        # 5. 逐张导入
        success = 0
        for i, (img_path, xml_path) in enumerate(pairs, 1):
            doc = parse_voc(xml_path)
            file_size = img_path.stat().st_size
            minio_path = f"{settings.dataset_minio_prefix}/{doc.file_name}"

            # 上传 MinIO
            upload_file(
                minio_client,
                settings.minio_bucket,
                minio_path,
                img_path,
                content_type="image/jpeg",
            )

            # 写 MySQL
            image_id = db.insert_image(
                conn,
                version_id=version_id,
                file_name=doc.file_name,
                class_name=doc.class_name,
                width=doc.width,
                height=doc.height,
                depth=doc.depth,
                file_size=file_size,
                minio_path=minio_path,
                split="raw",
            )
            for bbox in doc.objects:
                db.insert_annotation(
                    conn,
                    image_id=image_id,
                    class_name=bbox.class_name,
                    xmin=bbox.xmin,
                    ymin=bbox.ymin,
                    xmax=bbox.xmax,
                    ymax=bbox.ymax,
                )

            success += 1
            if i % batch_commit == 0:
                conn.commit()
                print(f"[Importer] 进度 {i}/{len(pairs)}")

        conn.commit()
        print(f"[Importer] 导入完成: {success}/{len(pairs)}")

        # 6. 更新版本状态
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dataset_version SET status=%s WHERE id=%s",
                ("ready", version_id),
            )
        conn.commit()

        return version_id, report
    except Exception as e:
        conn.rollback()
        print(f"[Importer] 导入失败, 已回滚: {e}")
        raise
    finally:
        conn.close()

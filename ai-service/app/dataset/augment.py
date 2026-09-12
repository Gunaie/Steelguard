"""数据增强模块: Albumentations 4 类增强, 原图+4=5 份 → 9000 张

增强方法(每图 ×4, 几何变换同步 bbox):
1. horizontal_flip  — 水平翻转
2. vertical_flip    — 垂直翻转
3. rotate           — 小角度旋转(±15°, Affine + 黑边常量填充)
4. brightness_contrast — 亮度对比度(仅像素值, bbox 不变)

注意: 不能用 A.Rotate(limit, border_mode=REFLECT) —— albumentations 2.x 对贴边
大框(如 crazing_1 的 191×192 框)旋转裁剪会产生多个碎片框(1 框→5 框)。
改用 A.Affine(rotate, border_mode=BORDER_CONSTANT) + BboxParams(min_visibility=0.5),
实测全量 4189 框 → 4176 框(99.69% 保留), 无重复。

流程:
1. 查询原始图记录(version_id=v1-raw, split=raw)
2. 创建增强版本 v1-aug5
3. 逐张读取 → 4 种增强 → 上传 MinIO → 写 MySQL
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import albumentations as A
import cv2
import numpy as np
import pymysql
from PIL import Image

from app.config import settings
from app.dataset import db
from app.dataset.minio_client import ensure_bucket, get_minio_client


def _bbox_params() -> A.BboxParams:
    """统一 bbox 参数: 旋转后可见面积不足原框 50% 的碎片框丢弃(翻转/亮度不受影响)"""
    return A.BboxParams(
        format="pascal_voc",
        label_fields=["labels"],
        min_visibility=0.5,
    )


# 4 种增强配置: 方法名 -> Albumentations 变换
AUGMENT_METHODS: dict[str, A.Compose] = {
    "horizontal_flip": A.Compose(
        [A.HorizontalFlip(p=1.0)],
        bbox_params=_bbox_params(),
    ),
    "vertical_flip": A.Compose(
        [A.VerticalFlip(p=1.0)],
        bbox_params=_bbox_params(),
    ),
    "rotate": A.Compose(
        # BORDER_CONSTANT=0: 旋转露出的角用黑色填充, 避免贴边大框裁剪产生碎片框
        [A.Affine(rotate=(-15, 15), p=1.0, border_mode=cv2.BORDER_CONSTANT)],
        bbox_params=_bbox_params(),
    ),
    "brightness_contrast": A.Compose(
        [A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=1.0)],
        bbox_params=_bbox_params(),
    ),
}


def _load_image_rgb(img_path: Path) -> np.ndarray:
    """读取灰度图转 RGB(3 通道复制), 兼容 Albumentations"""
    img = Image.open(img_path)
    return np.array(img.convert("RGB"))


def _augment_one(
    img_array: np.ndarray,
    bboxes: list[list[float]],
    labels: list[str],
    method: str,
) -> tuple[np.ndarray, list[list[float]], list[str]]:
    """对一张图应用指定增强

    Returns:
        (augmented_image, transformed_bboxes, labels)
    """
    transform = AUGMENT_METHODS[method]
    result = transform(image=img_array, bboxes=bboxes, labels=labels)
    return result["image"], result["bboxes"], result["labels"]


def _upload_array_to_minio(
    client,
    bucket: str,
    object_path: str,
    img_array: np.ndarray,
) -> int:
    """将 numpy 数组转 JPEG 上传到 MinIO, 返回文件大小"""
    img = Image.fromarray(img_array).convert("L")  # 转回灰度
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    size = buf.getbuffer().nbytes
    buf.seek(0)
    client.put_object(
        bucket_name=bucket,
        object_name=object_path,
        data=buf,
        length=size,
        content_type="image/jpeg",
    )
    return size


def augment_dataset(
    raw_version_id: int,
    aug_version: str = "v1-aug5",
    batch_commit: int = 50,
) -> tuple[int, int]:
    """对已导入的原始数据集做增强

    Args:
        raw_version_id: 原始版本 ID(读取源图)
        aug_version: 增强版本号
        batch_commit: 每多少张提交一次

    Returns:
        (aug_version_id, augmented_image_count)
    """
    conn = db.get_connection()
    try:
        # 查询原始图记录
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                """SELECT id, file_name, class_name, width, height, depth, minio_path
                   FROM dataset_image
                   WHERE version_id=%s AND split='raw' AND deleted=0
                   ORDER BY id""",
                (raw_version_id,),
            )
            raw_images = cur.fetchall()

        if not raw_images:
            raise RuntimeError(f"原始版本 {raw_version_id} 无图片记录")

        # 查询原始版本信息
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT image_count, annotation_count FROM dataset_version WHERE id=%s",
                (raw_version_id,),
            )
            raw_info = cur.fetchone()

        print(f"[Augment] 原始版本 {raw_version_id}: {len(raw_images)} 图")

        # 计算增强后总数
        n_methods = len(AUGMENT_METHODS)
        aug_total = len(raw_images) * n_methods
        total_with_raw = len(raw_images) * (n_methods + 1)  # 原图+增强
        print(f"[Augment] 增强方法 {n_methods} 种, 增强图 {aug_total}, 合计(含原图) {total_with_raw}")

        # 创建增强版本(annotation_count 先置 0, 跑完按实际入库标注数回填)
        aug_version_id = db.create_version(
            conn,
            version=aug_version,
            dataset_name="NEU-DET",
            source="NEU-DET augmented (Albumentations)",
            image_count=len(raw_images),
            annotation_count=0,
            augment_factor=n_methods + 1,
            total_count=total_with_raw,
            status="importing",
            remark=f"原图{n_methods}种增强, 共{total_with_raw}张",
        )
        print(f"[Augment] 增强版本 {aug_version} -> version_id={aug_version_id}")

        # MinIO
        minio_client = get_minio_client()
        ensure_bucket(minio_client, settings.minio_bucket)

        # 定位原始图本地路径: 相对路径优先相对 CWD, 不存在时回退到项目根目录
        project_root = Path(settings.dataset_root)
        if not project_root.is_absolute() and not project_root.exists():
            project_root = Path(__file__).resolve().parents[3] / settings.dataset_root
        project_root = project_root.resolve()
        images_dir = project_root / settings.dataset_images_dir

        # 逐张增强
        aug_count = 0
        aug_ann_count = 0
        for raw_idx, ri in enumerate(raw_images, 1):
            img_path = images_dir / ri["file_name"]
            if not img_path.exists():
                print(f"[Augment] 警告: 原始图缺失 {img_path}, 跳过")
                continue

            img_array = _load_image_rgb(img_path)

            # 查询该图所有标注框
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT class_name, xmin, ymin, xmax, ymax "
                    "FROM dataset_annotation WHERE image_id=%s ORDER BY id",
                    (ri["id"],),
                )
                anns = cur.fetchall()

            bboxes = [[a[1], a[2], a[3], a[4]] for a in anns]  # [xmin,ymin,xmax,ymax]
            labels = [a[0] for a in anns]

            stem = Path(ri["file_name"]).stem  # 如 crazing_1

            for method_name in AUGMENT_METHODS:
                aug_img, aug_bboxes, aug_labels = _augment_one(
                    img_array, bboxes, labels, method_name
                )

                aug_file_name = f"{stem}_{method_name}.jpg"
                aug_minio_path = f"{settings.dataset_augment_prefix}/{aug_file_name}"

                file_size = _upload_array_to_minio(
                    minio_client,
                    settings.minio_bucket,
                    aug_minio_path,
                    aug_img,
                )

                # 写 MySQL
                image_id = db.insert_image(
                    conn,
                    version_id=aug_version_id,
                    file_name=aug_file_name,
                    class_name=ri["class_name"],
                    width=ri["width"],
                    height=ri["height"],
                    depth=ri["depth"],
                    file_size=file_size,
                    minio_path=aug_minio_path,
                    split="augmented",
                    source_image_id=ri["id"],
                    augment_method=method_name,
                )

                # 写标注(Albumentations 返回的 bbox 可能被裁剪, 需 clamp)
                for bbox, label in zip(aug_bboxes, aug_labels):
                    xmin = max(0, int(round(bbox[0])))
                    ymin = max(0, int(round(bbox[1])))
                    xmax = min(ri["width"], int(round(bbox[2])))
                    ymax = min(ri["height"], int(round(bbox[3])))
                    # 跳过无效框(旋转后可能产生)
                    if xmin < xmax and ymin < ymax:
                        db.insert_annotation(
                            conn,
                            image_id=image_id,
                            class_name=label,
                            xmin=xmin,
                            ymin=ymin,
                            xmax=xmax,
                            ymax=ymax,
                        )
                        aug_ann_count += 1

                aug_count += 1

            if raw_idx % batch_commit == 0:
                conn.commit()
                print(f"[Augment] 进度: 已处理 {aug_count}/{aug_total} 增强图")

        conn.commit()
        print(f"[Augment] 增强完成: {aug_count}/{aug_total}, 标注框 {aug_ann_count}")

        # 回填实际标注数 + 更新版本状态
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dataset_version SET annotation_count=%s, status=%s WHERE id=%s",
                (aug_ann_count, "ready", aug_version_id),
            )
        conn.commit()

        return aug_version_id, aug_count
    except Exception as e:
        conn.rollback()
        print(f"[Augment] 失败, 已回滚: {e}")
        raise
    finally:
        conn.close()

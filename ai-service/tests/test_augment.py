"""数据增强 bbox 同步变换单元测试

只测纯函数 _augment_one(不连 MinIO/MySQL), 验证:
- 水平/垂直翻转后 bbox 坐标按 200×200 镜像
- 亮度对比度仅改像素, bbox 不变
- 旋转后框数量不丢失且坐标仍在图像范围内
- 多框一起变换保持数量与标签顺序
"""
from __future__ import annotations

import numpy as np

from app.dataset.augment import AUGMENT_METHODS, _augment_one

IMG = 200


def _img() -> np.ndarray:
    return np.zeros((IMG, IMG, 3), dtype=np.uint8)


def test_horizontal_flip_bbox():
    # [10,20,50,60] 水平镜像 -> [200-50,20,200-10,60]
    _, bboxes, labels = _augment_one(
        _img(), [[10, 20, 50, 60]], ["crazing"], "horizontal_flip"
    )
    assert labels == ["crazing"]
    assert len(bboxes) == 1
    xmin, ymin, xmax, ymax = bboxes[0]
    assert (round(xmin), round(ymin), round(xmax), round(ymax)) == (150, 20, 190, 60)


def test_vertical_flip_bbox():
    _, bboxes, _ = _augment_one(
        _img(), [[10, 20, 50, 60]], ["patches"], "vertical_flip"
    )
    xmin, ymin, xmax, ymax = bboxes[0]
    assert (round(xmin), round(ymin), round(xmax), round(ymax)) == (10, 140, 50, 180)


def test_brightness_contrast_keeps_bbox():
    _, bboxes, _ = _augment_one(
        _img(), [[10, 20, 50, 60]], ["inclusion"], "brightness_contrast"
    )
    xmin, ymin, xmax, ymax = bboxes[0]
    assert (round(xmin), round(ymin), round(xmax), round(ymax)) == (10, 20, 50, 60)


def test_rotate_keeps_box_count_in_bounds():
    _, bboxes, labels = _augment_one(
        _img(), [[10, 20, 50, 60]], ["scratches"], "rotate"
    )
    assert len(bboxes) == 1 and labels == ["scratches"]
    xmin, ymin, xmax, ymax = bboxes[0]
    assert 0 <= xmin < xmax <= IMG
    assert 0 <= ymin < ymax <= IMG


def test_rotate_edge_hugging_big_box_not_duplicated():
    """回归: albumentations 2.x 对贴边大框旋转曾产生碎片框(1 框→5 框)。

    NEU-DET crazing_1 的框为 [2,2,193,194](几乎铺满 200×200),
    用 Affine+BORDER_CONSTANT+min_visibility 后必须仍是 1 个框。
    """
    big_box = [[2, 2, 193, 194]]
    # 多次调用覆盖不同随机角度
    for _ in range(10):
        _, bboxes, labels = _augment_one(
            _img(), big_box, ["crazing"], "rotate"
        )
        assert len(bboxes) == 1, f"贴边大框被拆成 {len(bboxes)} 个碎片框"
        assert labels == ["crazing"]


def test_multi_box_transform_preserves_count():
    boxes = [[10, 10, 40, 40], [60, 60, 100, 120], [130, 130, 190, 190]]
    labels = ["inclusion", "patches", "inclusion"]
    for method in AUGMENT_METHODS:
        _, bboxes, out_labels = _augment_one(_img(), boxes, labels, method)
        assert len(bboxes) == 3, f"{method} 丢失框"
        assert out_labels == labels
        for xmin, ymin, xmax, ymax in bboxes:
            assert 0 <= xmin < xmax <= IMG
            assert 0 <= ymin < ymax <= IMG

"""yolo_export 纯函数单测: VOC->YOLO 坐标转换 + 标签文件写出"""
from __future__ import annotations

from pathlib import Path

from app.dataset.voc_parser import BBox, VOCDocument
from app.dataset.yolo_export import (
    CLASS_TO_ID,
    YOLO_CLASSES,
    voc_bbox_to_yolo,
    write_yolo_label,
)


def test_classes_are_six_alphabetical_stable():
    assert YOLO_CLASSES == [
        "crazing",
        "inclusion",
        "patches",
        "pitted_surface",
        "rolled-in_scale",
        "scratches",
    ]
    assert CLASS_TO_ID["crazing"] == 0
    assert CLASS_TO_ID["scratches"] == 5


def test_bbox_center_normalized():
    # 整图框(0,0,200,200) -> 中心点 0.5, 宽高 1.0
    cx, cy, w, h = voc_bbox_to_yolo(0, 0, 200, 200, 200, 200)
    assert (cx, cy, w, h) == (0.5, 0.5, 1.0, 1.0)


def test_bbox_known_quadrant():
    # 左上 1/4 区域框
    cx, cy, w, h = voc_bbox_to_yolo(0, 0, 100, 100, 200, 200)
    assert abs(cx - 0.25) < 1e-9
    assert abs(cy - 0.25) < 1e-9
    assert w == 0.5
    assert h == 0.5


def test_bbox_non_square_image():
    # 非方图归一化按各自轴独立计算
    cx, cy, w, h = voc_bbox_to_yolo(10, 20, 50, 80, 100, 200)
    assert abs(cx - 0.3) < 1e-9
    assert abs(cy - 0.25) < 1e-9
    assert w == 0.4
    assert h == 0.3


def test_write_yolo_label_multi_object(tmp_path: Path):
    doc = VOCDocument(
        file_name="inclusion_1.jpg",
        width=200,
        height=200,
        depth=1,
        objects=[
            BBox("crazing", 0, 0, 100, 100),
            BBox("scratches", 50, 50, 200, 200),
        ],
    )
    label = tmp_path / "inclusion_1.txt"
    n = write_yolo_label(label, doc)
    assert n == 2
    lines = label.read_text(encoding="utf-8").splitlines()
    assert lines[0].split()[0] == "0"
    assert lines[1].split()[0] == "5"
    for line in lines:
        parts = line.split()
        values = [float(v) for v in parts[1:]]
        assert all(0.0 <= v <= 1.0 for v in values)


def test_duplicate_bboxes_deduped(tmp_path: Path):
    """NEU-DET 源数据 3 个 xml 含完全重复框, 导出必须去重(对应 crazing_120)"""
    doc = VOCDocument(
        file_name="crazing_120.jpg",
        width=200,
        height=200,
        depth=1,
        objects=[
            BBox("crazing", 1, 81, 117, 146),
            BBox("crazing", 1, 81, 117, 146),  # 与上框完全相同
            BBox("crazing", 83, 6, 178, 57),
        ],
    )
    label = tmp_path / "crazing_120.txt"
    n = write_yolo_label(label, doc)
    assert n == 2  # 3 个框 -> 去重后 2 行
    assert len(label.read_text(encoding="utf-8").splitlines()) == 2

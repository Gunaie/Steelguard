"""EDA 统计模块单元测试(合成小数据集, 不依赖真实 NEU-DET)"""
from __future__ import annotations

from app.dataset.eda import run_eda


def test_eda_basic_counts(make_dataset):
    images_dir, ann_dir = make_dataset([
        ("crazing_1", [("crazing", 0, 0, 50, 50)]),
        ("inclusion_1", [
            ("inclusion", 0, 0, 20, 20),
            ("inclusion", 100, 100, 180, 180),
        ]),
        ("patches_1", [
            ("patches", 0, 0, 30, 30),
            ("inclusion", 0, 0, 40, 40),  # 跨类多框图
        ]),
    ])
    report = run_eda(images_dir, ann_dir)

    assert report.total_images == 3
    assert report.total_annotations == 5
    # 每图框数分布: 1框×1, 2框×2
    assert report.bbox_per_image == {1: 1, 2: 2}
    # 类别框数
    assert report.class_bbox_count == {
        "crazing": 1,
        "inclusion": 3,
        "patches": 1,
    }
    # 图片数(跨类图在两个类各计一次)
    assert report.class_image_count["inclusion"] == 2
    assert report.class_image_count["patches"] == 1
    # bbox 宽高收集(5 个框: 50/20/80/30/40)
    assert sorted(report.bbox_widths) == [20, 30, 40, 50, 80]
    assert report.width_set == {200} and report.depth_set == {1}


def test_eda_to_dict_serializable(make_dataset):
    images_dir, ann_dir = make_dataset([
        ("scratches_1", [("scratches", 10, 10, 60, 90)]),
    ])
    d = run_eda(images_dir, ann_dir).to_dict()
    assert d["total_images"] == 1
    assert d["total_annotations"] == 1
    assert d["class_distribution"][0]["class_name"] == "scratches"
    assert d["bbox_size_stats"]["width_mean"] == 50
    assert d["bbox_size_stats"]["height_mean"] == 80

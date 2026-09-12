"""EDA 统计模块

对 VOC 数据集做探索性数据分析:
- 类别分布(每类图片数 + 框数)
- 每图框数分布
- 图像尺寸统计
- bbox 尺寸分布(宽高统计)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from app.dataset.voc_parser import BBox, VOCDocument, find_voc_files, parse_voc


@dataclass
class EDAReport:
    """EDA 统计报告"""
    total_images: int = 0
    total_annotations: int = 0
    # 类别 -> 图片数
    class_image_count: Dict[str, int] = field(default_factory=dict)
    # 类别 -> 框数
    class_bbox_count: Dict[str, int] = field(default_factory=dict)
    # 每图框数 -> 图片数 (1框, 2框, ...)
    bbox_per_image: Dict[int, int] = field(default_factory=dict)
    # 尺寸分布
    width_set: set = field(default_factory=set)
    height_set: set = field(default_factory=set)
    depth_set: set = field(default_factory=set)
    # bbox 宽高统计
    bbox_widths: List[int] = field(default_factory=list)
    bbox_heights: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转 dict 用于 API 响应"""
        return {
            "total_images": self.total_images,
            "total_annotations": self.total_annotations,
            "class_distribution": [
                {"class_name": cls, "image_count": self.class_image_count.get(cls, 0),
                 "bbox_count": self.class_bbox_count.get(cls, 0)}
                for cls in sorted(self.class_image_count.keys())
            ],
            "bbox_per_image_distribution": [
                {"bbox_count": k, "image_count": v}
                for k, v in sorted(self.bbox_per_image.items())
            ],
            "size_stats": {
                "widths": sorted(self.width_set),
                "heights": sorted(self.height_set),
                "depths": sorted(self.depth_set),
            },
            "bbox_size_stats": {
                "width_mean": round(sum(self.bbox_widths) / max(len(self.bbox_widths), 1), 2),
                "height_mean": round(sum(self.bbox_heights) / max(len(self.bbox_heights), 1), 2),
                "width_min": min(self.bbox_widths) if self.bbox_widths else 0,
                "width_max": max(self.bbox_widths) if self.bbox_widths else 0,
                "height_min": min(self.bbox_heights) if self.bbox_heights else 0,
                "height_max": max(self.bbox_heights) if self.bbox_heights else 0,
                "total_bboxes": len(self.bbox_widths),
            },
        }


def run_eda(images_dir: str | Path, annotations_dir: str | Path) -> EDAReport:
    """对整个数据集跑 EDA

    Args:
        images_dir: 图片目录
        annotations_dir: VOC XML 目录

    Returns:
        EDAReport 统计报告
    """
    pairs = find_voc_files(images_dir, annotations_dir)
    report = EDAReport(total_images=len(pairs))

    for img_path, xml_path in pairs:
        doc = parse_voc(xml_path)

        # 尺寸
        report.width_set.add(doc.width)
        report.height_set.add(doc.height)
        report.depth_set.add(doc.depth)

        # 框数分布
        n_boxes = len(doc.objects)
        report.bbox_per_image[n_boxes] = report.bbox_per_image.get(n_boxes, 0) + 1

        # 类别统计
        classes_on_image: set = set()
        for bbox in doc.objects:
            classes_on_image.add(bbox.class_name)
            report.class_bbox_count[bbox.class_name] = report.class_bbox_count.get(bbox.class_name, 0) + 1
            report.total_annotations += 1
            # bbox 宽高
            report.bbox_widths.append(bbox.xmax - bbox.xmin)
            report.bbox_heights.append(bbox.ymax - bbox.ymin)

        for cls in classes_on_image:
            report.class_image_count[cls] = report.class_image_count.get(cls, 0) + 1

    return report


def print_eda_report(report: EDAReport) -> None:
    """打印 EDA 报告到控制台"""
    print("=" * 60)
    print("NEU-DET 数据集 EDA 报告")
    print("=" * 60)
    print(f"总图片数: {report.total_images}")
    print(f"总标注框数: {report.total_annotations}")
    print(f"平均每图框数: {report.total_annotations / max(report.total_images, 1):.2f}")
    print()

    print("--- 类别分布 ---")
    print(f"{'类别':<20} {'图片数':>8} {'框数':>8}")
    for cls in sorted(report.class_image_count.keys()):
        print(f"{cls:<20} {report.class_image_count[cls]:>8} {report.class_bbox_count.get(cls, 0):>8}")
    print()

    print("--- 每图框数分布 ---")
    for k in sorted(report.bbox_per_image.keys()):
        print(f"  {k} 框/图: {report.bbox_per_image[k]} 张")
    print()

    print("--- 尺寸统计 ---")
    print(f"  宽度集合: {sorted(report.width_set)}")
    print(f"  高度集合: {sorted(report.height_set)}")
    print(f"  通道集合: {sorted(report.depth_set)}")
    print()

    print("--- bbox 尺寸统计 ---")
    d = report.to_dict()["bbox_size_stats"]
    print(f"  宽度: min={d['width_min']} max={d['width_max']} mean={d['width_mean']}")
    print(f"  高度: min={d['height_min']} max={d['height_max']} mean={d['height_mean']}")
    print("=" * 60)

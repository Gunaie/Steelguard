"""pytest 公共夹具: 生成合成 VOC XML / 空 jpg 的辅助函数"""
from __future__ import annotations

from pathlib import Path

import pytest


def make_voc_xml(
    xml_path: Path,
    objects: list[tuple[str, int, int, int, int]],
    width: int = 200,
    height: int = 200,
    depth: int = 1,
    filename: str | None = None,
) -> Path:
    """生成一个 VOC XML 文件

    Args:
        objects: [(class_name, xmin, ymin, xmax, ymax), ...]
        filename: <filename> 标签内容; None 时用 xml stem + .jpg
    """
    stem = xml_path.stem
    fn = filename if filename is not None else f"{stem}.jpg"
    lines = [
        "<annotation>",
        f"  <filename>{fn}</filename>",
        "  <size>",
        f"    <width>{width}</width>",
        f"    <height>{height}</height>",
        f"    <depth>{depth}</depth>",
        "  </size>",
    ]
    for name, xmin, ymin, xmax, ymax in objects:
        lines += [
            "  <object>",
            f"    <name>{name}</name>",
            "    <bndbox>",
            f"      <xmin>{xmin}</xmin>",
            f"      <ymin>{ymin}</ymin>",
            f"      <xmax>{xmax}</xmax>",
            f"      <ymax>{ymax}</ymax>",
            "    </bndbox>",
            "  </object>",
        ]
    lines.append("</annotation>")
    xml_path.write_text("\n".join(lines), encoding="utf-8")
    return xml_path


def make_pair(
    images_dir: Path,
    annotations_dir: Path,
    stem: str,
    objects: list[tuple[str, int, int, int, int]],
    **kwargs,
) -> tuple[Path, Path]:
    """生成一对空 jpg + VOC xml(run_eda 只读 xml, 不打开图片)"""
    img = images_dir / f"{stem}.jpg"
    img.write_bytes(b"")
    xml = make_voc_xml(annotations_dir / f"{stem}.xml", objects, **kwargs)
    return img, xml


@pytest.fixture
def make_dataset(tmp_path: Path):
    """返回夹具函数, 快速构造 (images_dir, annotations_dir)"""
    images_dir = tmp_path / "IMAGES"
    annotations_dir = tmp_path / "ANNOTATIONS"
    images_dir.mkdir()
    annotations_dir.mkdir()

    def _make(pairs: list[tuple[str, list]]):
        for stem, objects in pairs:
            make_pair(images_dir, annotations_dir, stem, objects)
        return images_dir, annotations_dir

    return _make

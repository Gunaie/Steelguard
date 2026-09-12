"""VOC XML 标注解析器

NEU-DET 数据集格式:
- 200×200 灰度 jpg, depth=1
- VOC 格式 xml, 一图可多框
- 文件名前缀 = 标准类名全名(非缩写): crazing/inclusion/patches/pitted_surface/rolled-in_scale/scratches
- bbox 为 PascalVOC 绝对像素坐标 xmin/ymin/xmax/ymax
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# NEU-DET 6 类标准类名
VALID_CLASSES = frozenset({
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
})


class VOCParseError(ValueError):
    """VOC 解析异常: 文件缺失/格式非法/类名未知/坐标越界"""


@dataclass
class BBox:
    """单个标注框"""
    class_name: str
    xmin: int
    ymin: int
    xmax: int
    ymax: int

    def __post_init__(self):
        if self.xmin < 0 or self.ymin < 0:
            raise VOCParseError(f"坐标不能为负: xmin={self.xmin}, ymin={self.ymin}")
        if self.xmin >= self.xmax:
            raise VOCParseError(
                f"xmin 必须小于 xmax: xmin={self.xmin}, xmax={self.xmax}"
            )
        if self.ymin >= self.ymax:
            raise VOCParseError(
                f"ymin 必须小于 ymax: ymin={self.ymin}, ymax={self.ymax}"
            )
        if self.class_name not in VALID_CLASSES:
            raise VOCParseError(
                f"未知类名 '{self.class_name}', 合法类: {sorted(VALID_CLASSES)}"
            )


@dataclass
class VOCDocument:
    """一个 VOC XML 文档的解析结果"""
    file_name: str           # 图片文件名(含扩展名)
    width: int
    height: int
    depth: int
    objects: List[BBox] = field(default_factory=list)

    @property
    def class_name(self) -> str:
        """该图的主类名(取第一个标注框的类名)"""
        if not self.objects:
            raise VOCParseError("文档无任何标注框")
        return self.objects[0].class_name


def parse_voc(xml_path: str | Path) -> VOCDocument:
    """解析单个 VOC XML 文件

    Args:
        xml_path: XML 文件路径

    Returns:
        VOCDocument 解析结果

    Raises:
        VOCParseError: 文件不存在/格式错误/类名非法/坐标越界
    """
    xml_path = Path(xml_path)
    if not xml_path.exists():
        raise VOCParseError(f"标注文件不存在: {xml_path}")
    if xml_path.suffix.lower() != ".xml":
        raise VOCParseError(f"非 XML 文件: {xml_path}")

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        raise VOCParseError(f"XML 解析失败 {xml_path}: {e}") from e

    root = tree.getroot()

    # 解析 size
    size_elem = root.find("size")
    if size_elem is None:
        raise VOCParseError(f"<size> 缺失: {xml_path}")

    def _get_int(parent, tag: str, context: str) -> int:
        elem = parent.find(tag)
        if elem is None or elem.text is None:
            raise VOCParseError(f"<{tag}> 缺失: {context}")
        try:
            return int(elem.text)
        except ValueError as e:
            raise VOCParseError(f"<{tag}> 非整数 '{elem.text}': {context}") from e

    width = _get_int(size_elem, "width", str(xml_path))
    height = _get_int(size_elem, "height", str(xml_path))
    depth = _get_int(size_elem, "depth", str(xml_path))

    if width <= 0 or height <= 0:
        raise VOCParseError(
            f"图像尺寸非法 width={width} height={height}: {xml_path}"
        )

    # 解析 filename(NEU-DET 镜像中 174 个 xml 的 <filename> 缺 .jpg 后缀, 统一归一化)
    filename_elem = root.find("filename")
    if filename_elem is not None and filename_elem.text:
        file_name = filename_elem.text.strip()
    else:
        file_name = xml_path.stem
    if not Path(file_name).suffix:
        file_name += ".jpg"

    # 解析 objects
    objects: List[BBox] = []
    for obj in root.findall("object"):
        name_elem = obj.find("name")
        if name_elem is None or not name_elem.text:
            raise VOCParseError(f"<object><name> 缺失: {xml_path}")
        class_name = name_elem.text.strip()

        bndbox = obj.find("bndbox")
        if bndbox is None:
            raise VOCParseError(f"<bndbox> 缺失: {xml_path}")

        xmin = _get_int(bndbox, "xmin", f"{xml_path}#{class_name}")
        ymin = _get_int(bndbox, "ymin", f"{xml_path}#{class_name}")
        xmax = _get_int(bndbox, "xmax", f"{xml_path}#{class_name}")
        ymax = _get_int(bndbox, "ymax", f"{xml_path}#{class_name}")

        # 校验坐标不越界(允许 xmax==width / ymax==height)
        if xmin < 0 or ymin < 0 or xmax > width or ymax > height:
            raise VOCParseError(
                f"框坐标越界 [{class_name}] "
                f"({xmin},{ymin},{xmax},{ymax}) 尺寸({width}×{height}): {xml_path}"
            )

        bbox = BBox(class_name=class_name, xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
        objects.append(bbox)

    if not objects:
        raise VOCParseError(f"文档无任何标注框: {xml_path}")

    return VOCDocument(
        file_name=file_name,
        width=width,
        height=height,
        depth=depth,
        objects=objects,
    )


def find_voc_files(images_dir: str | Path, annotations_dir: str | Path) -> List[tuple[Path, Path]]:
    """扫描目录, 返回 (图片路径, 标注路径) 配对列表

    Args:
        images_dir: 图片目录
        annotations_dir: VOC XML 目录

    Returns:
        [(img_path, xml_path), ...] 列表, 按 file_name 排序

    Raises:
        VOCParseError: 图片-标注配对缺失
    """
    images_dir = Path(images_dir)
    annotations_dir = Path(annotations_dir)

    if not images_dir.exists():
        raise VOCParseError(f"图片目录不存在: {images_dir}")
    if not annotations_dir.exists():
        raise VOCParseError(f"标注目录不存在: {annotations_dir}")

    pairs: List[tuple[Path, Path]] = []
    img_files = sorted(images_dir.glob("*.jpg"))
    if not img_files:
        raise VOCParseError(f"图片目录无 .jpg 文件: {images_dir}")

    for img in img_files:
        xml = annotations_dir / f"{img.stem}.xml"
        if not xml.exists():
            raise VOCParseError(f"标注缺失: 图片={img.name} 期望标注={xml.name}")
        pairs.append((img, xml))

    return pairs

"""VOC 解析器单元测试

覆盖验收要求「单元测试校验标注文件格式」:
- 合法 xml: 单框/多框/6 类全名/边界坐标
- NEU-DET 镜像坑: <filename> 缺 .jpg 后缀自动补全
- 异常: 文件不存在/非 xml/XML 格式坏/size 缺失/非法类名/
        坐标为负/xmin>=xmax/坐标越界/无标注框/标注配对缺失
"""
from __future__ import annotations

import pytest

from app.dataset.voc_parser import (
    VALID_CLASSES,
    BBox,
    VOCParseError,
    find_voc_files,
    parse_voc,
)
from conftest import make_pair, make_voc_xml


def test_parse_single_box(tmp_path):
    xml = make_voc_xml(
        tmp_path / "crazing_1.xml",
        [("crazing", 10, 20, 100, 120)],
    )
    doc = parse_voc(xml)
    assert doc.file_name == "crazing_1.jpg"
    assert (doc.width, doc.height, doc.depth) == (200, 200, 1)
    assert len(doc.objects) == 1
    assert doc.class_name == "crazing"
    b = doc.objects[0]
    assert (b.xmin, b.ymin, b.xmax, b.ymax) == (10, 20, 100, 120)


def test_parse_multi_box(tmp_path):
    """一图多框(NEU-DET 常见), 且允许跨类"""
    xml = make_voc_xml(
        tmp_path / "inclusion_1.xml",
        [
            ("inclusion", 1, 2, 50, 60),
            ("inclusion", 70, 80, 199, 199),
            ("patches", 100, 100, 150, 150),
        ],
    )
    doc = parse_voc(xml)
    assert len(doc.objects) == 3
    assert doc.class_name == "inclusion"
    assert {b.class_name for b in doc.objects} == {"inclusion", "patches"}


def test_all_six_valid_classes(tmp_path):
    for i, cls in enumerate(sorted(VALID_CLASSES)):
        xml = make_voc_xml(tmp_path / f"{cls}_{i}.xml", [(cls, 1, 1, 50, 50)])
        assert parse_voc(xml).class_name == cls


def test_bbox_touching_boundary_ok(tmp_path):
    """xmax==width / ymax==height 合法; xmin=ymin=0 合法"""
    xml = make_voc_xml(
        tmp_path / "edge.xml",
        [("scratches", 0, 0, 200, 200)],
    )
    b = parse_voc(xml).objects[0]
    assert (b.xmax, b.ymax) == (200, 200)


def test_filename_without_extension_normalized(tmp_path):
    """镜像中部分 xml <filename> 缺 .jpg 后缀(如 crazing_1), 需归一化"""
    xml = make_voc_xml(
        tmp_path / "crazing_2.xml",
        [("crazing", 1, 1, 50, 50)],
        filename="crazing_2",
    )
    assert parse_voc(xml).file_name == "crazing_2.jpg"


def test_bbox_dataclass_rejects_invalid():
    with pytest.raises(VOCParseError):
        BBox("crazing", -1, 0, 10, 10)  # 负坐标
    with pytest.raises(VOCParseError):
        BBox("crazing", 10, 0, 10, 50)  # xmin == xmax
    with pytest.raises(VOCParseError):
        BBox("crazing", 0, 60, 50, 50)  # ymin > ymax
    with pytest.raises(VOCParseError):
        BBox("not_a_class", 0, 0, 10, 10)  # 非法类名


def test_unknown_class_in_xml(tmp_path):
    xml = make_voc_xml(tmp_path / "bad.xml", [("rust", 1, 1, 50, 50)])
    with pytest.raises(VOCParseError, match="未知类名"):
        parse_voc(xml)


def test_bbox_out_of_image(tmp_path):
    xml = make_voc_xml(tmp_path / "oob.xml", [("crazing", 1, 1, 201, 50)])
    with pytest.raises(VOCParseError, match="越界"):
        parse_voc(xml)


def test_missing_file_raises(tmp_path):
    with pytest.raises(VOCParseError, match="不存在"):
        parse_voc(tmp_path / "nope.xml")


def test_non_xml_suffix_raises(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(VOCParseError, match="非 XML"):
        parse_voc(f)


def test_malformed_xml_raises(tmp_path):
    f = tmp_path / "broken.xml"
    f.write_text("<annotation><size>")  # 未闭合
    with pytest.raises(VOCParseError, match="XML 解析失败"):
        parse_voc(f)


def test_missing_size_raises(tmp_path):
    f = tmp_path / "nosize.xml"
    f.write_text("<annotation><filename>x.jpg</filename></annotation>")
    with pytest.raises(VOCParseError, match="<size> 缺失"):
        parse_voc(f)


def test_no_object_raises(tmp_path):
    xml = make_voc_xml(tmp_path / "empty.xml", [])
    with pytest.raises(VOCParseError, match="无任何标注框"):
        parse_voc(xml)


def test_find_voc_files_pairs_and_sorts(tmp_path):
    images_dir = tmp_path / "IMAGES"
    ann_dir = tmp_path / "ANNOTATIONS"
    images_dir.mkdir()
    ann_dir.mkdir()
    make_pair(images_dir, ann_dir, "b_1", [("crazing", 1, 1, 10, 10)])
    make_pair(images_dir, ann_dir, "a_2", [("patches", 1, 1, 10, 10)])

    pairs = find_voc_files(images_dir, ann_dir)
    assert [p[0].name for p in pairs] == ["a_2.jpg", "b_1.jpg"]
    assert all(xml.exists() for _, xml in pairs)


def test_find_voc_files_missing_annotation(tmp_path):
    images_dir = tmp_path / "IMAGES"
    ann_dir = tmp_path / "ANNOTATIONS"
    images_dir.mkdir()
    ann_dir.mkdir()
    (images_dir / "orphan.jpg").write_bytes(b"")
    with pytest.raises(VOCParseError, match="标注缺失"):
        find_voc_files(images_dir, ann_dir)


def test_find_voc_files_empty_images(tmp_path):
    images_dir = tmp_path / "IMAGES"
    ann_dir = tmp_path / "ANNOTATIONS"
    images_dir.mkdir()
    ann_dir.mkdir()
    with pytest.raises(VOCParseError, match="无 .jpg"):
        find_voc_files(images_dir, ann_dir)

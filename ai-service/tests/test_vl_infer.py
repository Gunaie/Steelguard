"""VL 零样本检测器纯函数单测(不发起任何真实 HTTP 请求)"""
from __future__ import annotations

import pytest

from app.inference.vl_infer import VlError, canonical_class, parse_vl_content


# ---------- canonical_class ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("crazing", "crazing"),
        ("CRAZING", "crazing"),
        ("inclusions", "inclusion"),
        ("pitted surface", "pitted_surface"),
        ("pitted_surface", "pitted_surface"),
        ("rolled-in_scale", "rolled-in_scale"),
        ("rolled in scale", "rolled-in_scale"),
        ("rolled-in scale", "rolled-in_scale"),
        ("scratch", "scratches"),
        ("patches", "patches"),
        ("裂纹", "crazing"),
        ("夹杂", "inclusion"),
        ("斑块", "patches"),
        ("麻点", "pitted_surface"),
        ("氧化铁皮", "rolled-in_scale"),
        ("划痕", "scratches"),
    ],
)
def test_canonical_class_aliases(raw, expected):
    assert canonical_class(raw) == expected


@pytest.mark.parametrize("raw", ["dog", "", None, 123, "锈蚀"])
def test_canonical_class_rejects_unknown(raw):
    assert canonical_class(raw) is None


# ---------- parse_vl_content ----------

def test_parse_basic_normalized_to_pixel():
    content = '{"detections":[{"class":"scratches","confidence":0.8,' \
              '"bbox":{"x1":0.1,"y1":0.2,"x2":0.3,"y2":0.4}}]}'
    dets = parse_vl_content(content, 200, 100)
    assert len(dets) == 1
    d = dets[0]
    assert d["class_id"] == 5
    assert d["class_name"] == "scratches"
    assert d["class_name_cn"] == "划痕"
    assert d["confidence"] == 0.8
    # 归一化坐标按各自宽高换算
    assert d["bbox"] == {"x1": 20.0, "y1": 20.0, "x2": 60.0, "y2": 40.0}


def test_parse_strips_code_fence():
    content = '```json\n{"detections":[]}\n```'
    assert parse_vl_content(content, 200, 200) == []


def test_parse_bad_json_raises():
    with pytest.raises(VlError) as ei:
        parse_vl_content("我认为图中有划痕", 200, 200)
    assert ei.value.kind == "badresponse"


def test_parse_missing_detections_key_raises():
    with pytest.raises(VlError):
        parse_vl_content('{"boxes": []}', 200, 200)


def test_parse_trailing_comma_repaired():
    # 多框输出时模型偶发尾随逗号
    content = """{"detections":[
      {"class":"inclusion","confidence":0.7,"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2},},
      {"class":"patches","confidence":0.6,"bbox":{"x1":0.3,"y1":0.3,"x2":0.4,"y2":0.4},},
    ]}"""
    dets = parse_vl_content(content, 100, 100)
    assert [d["class_name"] for d in dets] == ["inclusion", "patches"]


def test_parse_unknown_class_and_bad_items_skipped():
    content = """{"detections":[
        {"class":"dog","confidence":0.9,"bbox":{"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5}},
        "garbage",
        {"class":"scratches","bbox":{"x1":0.1,"y1":0.1}},
        {"class":"patches","confidence":0.7,"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2}}
    ]}"""
    dets = parse_vl_content(content, 100, 100)
    assert len(dets) == 1
    assert dets[0]["class_name"] == "patches"


def test_parse_dropped_degenerate_and_clipped_boxes():
    content = """{"detections":[
        {"class":"scratches","bbox":{"x1":0.8,"y1":0.8,"x2":0.7,"y2":0.9}},
        {"class":"scratches","bbox":{"x1":-0.5,"y1":-0.5,"x2":1.5,"y2":1.5}},
        {"class":"scratches","bbox":{"x1":0.5,"y1":0.5,"x2":0.50001,"y2":0.50001}}
    ]}"""
    dets = parse_vl_content(content, 100, 100)
    # 第1个 x 反转 -> sorted 校正为 0.7/0.8, 保留(70,80,80,90)
    # 第2个越界裁剪到 0/0-1/1, 保留(0,0,100,100)
    # 第3个边长 0.00001 < 1e-4, 退化框丢弃
    assert len(dets) == 2
    assert dets[0]["bbox"] == {"x1": 70, "y1": 80, "x2": 80, "y2": 90}
    assert dets[1]["bbox"] == {"x1": 0, "y1": 0, "x2": 100, "y2": 100}


def test_parse_default_confidence_and_clamp():
    content = '{"detections":[{"class":"inclusion",' \
              '"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2},"confidence":1.9}]}'
    dets = parse_vl_content(content, 100, 100)
    assert dets[0]["confidence"] == 1.0

    content2 = '{"detections":[{"class":"inclusion",' \
               '"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2}}]}'
    dets2 = parse_vl_content(content2, 100, 100)
    assert dets2[0]["confidence"] == 0.5


def test_parse_sorted_by_confidence_desc():
    content = """{"detections":[
        {"class":"inclusion","confidence":0.3,"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2}},
        {"class":"patches","confidence":0.9,"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2}},
        {"class":"scratches","confidence":0.6,"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2}}
    ]}"""
    dets = parse_vl_content(content, 100, 100)
    assert [d["confidence"] for d in dets] == [0.9, 0.6, 0.3]


# ---------- 损坏/截断输出打捞(线上实测坏形态) ----------

def test_salvage_duplicate_key_and_truncated_tail():
    """模型写完完整对象后又重复 ", "detections": [...]" 并半截断尾"""
    content = """{
  "detections": [
    {"class":"crazing","confidence":0.9,"bbox":{"x1":0.05,"y1":0.05,"x2":0.35,"y2":0.45}},
    {"class":"crazing","confidence":0.85,"bbox":{"x1":0.4,"y1":0.4,"x2":0.7,"y2":0.6}}
  ]

  ,
  "detections": [
    {"class":"crazing","confidence":0.9,"bbox":{"x1":0.05,"y1":0.05,"x2":0.35,"""
    dets = parse_vl_content(content, 100, 100)
    # 只打捞第一段完整数组的 2 项, 重复段不计入
    assert len(dets) == 2
    assert dets[0]["bbox"] == {"x1": 5.0, "y1": 5.0, "x2": 35.0, "y2": 45.0}
    assert dets[1]["bbox"] == {"x1": 40.0, "y1": 40.0, "x2": 70.0, "y2": 60.0}


def test_salvage_truncated_mid_array():
    """数组中途截断、最后一个 item 不完整: 保留前面完整项"""
    content = """{"detections":[
      {"class":"scratches","confidence":0.9,"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.9}},
      {"class":"scratches","confidence":0.8,"bbox":{"x1":0.5,"y1":0.1,"x2":0.6,"y2":0.9}},
      {"class":"scratches","confidence":0.7,"bbox":{"x1":0.7,"y1":0.1,"""
    dets = parse_vl_content(content, 200, 200)
    assert len(dets) == 2
    assert dets[0]["class_name"] == "scratches"
    assert dets[1]["bbox"]["x1"] == 100.0


def test_salvage_trailing_junk_after_complete_object():
    """完整 JSON 后面跟解释性文字: raw_decode 直接容忍, 不需要打捞"""
    content = '{"detections":[{"class":"patches","confidence":0.7,' \
              '"bbox":{"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5}}]}\n以上是检测结果。'
    dets = parse_vl_content(content, 100, 100)
    assert len(dets) == 1
    assert dets[0]["class_name"] == "patches"


def test_salvage_trailing_comma_fragment_item():
    """打捞的单个 item 自带尾随逗号也能修复"""
    content = '{"detections":[{"class":"inclusion","confidence":0.6,' \
              '"bbox":{"x1":0.1,"y1":0.1,"x2":0.2,"y2":0.2},},' \
              '{"class":"inclusion","confidence":0.5,' \
              '"bbox":{"x1":0.3,"y1":0.3,"x2":0.4,"y2":0.4},}]}'
    dets = parse_vl_content(content, 100, 100)
    assert len(dets) == 2


def test_parse_unsalvageable_raises_badresponse():
    with pytest.raises(VlError) as ei:
        parse_vl_content("模型今天不想检测, 输出了一段纯文字", 100, 100)
    assert ei.value.kind == "badresponse"

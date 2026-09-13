"""阶段3 推理模块单测: 结果解析/坐标保护/图片解码/设备选择(不加载真实模型)"""
from __future__ import annotations

import sys
import types

import cv2
import numpy as np
import pytest

from app.inference.yolo_infer import (
    YOLO_CLASSES,
    decode_image,
    parse_detections,
    resolve_device,
)


class FakeTensor:
    """模拟 ultralytics boxes.xyxy/conf/cls 的 .cpu().numpy() 链"""

    def __init__(self, arr):
        self.arr = np.asarray(arr, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self.arr

    def astype(self, dtype):
        return FakeTensor(self.arr.astype(dtype))


class FakeBoxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = FakeTensor(xyxy)
        self.conf = FakeTensor(conf)
        self.cls = FakeTensor(cls)

    def __len__(self):
        return len(self.conf.arr)


NAMES = {i: name for i, name in enumerate(YOLO_CLASSES)}


def test_parse_empty_boxes():
    assert parse_detections(None, NAMES, 200, 200) == []
    assert parse_detections(FakeBoxes([], [], []), NAMES, 200, 200) == []


def test_parse_basic_fields_and_cn_name():
    boxes = FakeBoxes(
        xyxy=[[10.0, 20.0, 100.0, 120.0]],
        conf=[0.932],
        cls=[5],  # scratches
    )
    dets = parse_detections(boxes, NAMES, 200, 200)
    assert len(dets) == 1
    d = dets[0]
    assert d["class_id"] == 5
    assert d["class_name"] == "scratches"
    assert d["class_name_cn"] == "划痕"
    assert d["confidence"] == 0.932
    assert d["bbox"] == {"x1": 10.0, "y1": 20.0, "x2": 100.0, "y2": 120.0}


def test_parse_sorted_by_confidence_desc():
    boxes = FakeBoxes(
        xyxy=[[0, 0, 10, 10], [0, 0, 20, 20], [0, 0, 30, 30]],
        conf=[0.3, 0.9, 0.6],
        cls=[0, 1, 2],
    )
    dets = parse_detections(boxes, NAMES, 200, 200)
    assert [d["confidence"] for d in dets] == [0.9, 0.6, 0.3]


def test_parse_clamps_out_of_image_coords():
    boxes = FakeBoxes(
        xyxy=[[-50.0, -60.0, 300.0, 260.0]],
        conf=[0.8],
        cls=[0],
    )
    d = parse_detections(boxes, NAMES, 200, 200)[0]
    assert d["bbox"] == {"x1": 0.0, "y1": 0.0, "x2": 200.0, "y2": 200.0}


def test_parse_drops_degenerate_boxes():
    # 第二框 x2<=x1(截断后), 应丢弃
    boxes = FakeBoxes(
        xyxy=[[10.0, 10.0, 50.0, 50.0], [210.0, 10.0, 220.0, 50.0]],
        conf=[0.9, 0.8],
        cls=[0, 1],
    )
    dets = parse_detections(boxes, NAMES, 200, 200)
    assert len(dets) == 1
    assert dets[0]["class_id"] == 0


def test_class_order_is_alphabetical_neudet():
    """训练约定不可被无意改动(权重 names 与该顺序强校验)"""
    assert YOLO_CLASSES == [
        "crazing",
        "inclusion",
        "patches",
        "pitted_surface",
        "rolled-in_scale",
        "scratches",
    ]


def test_decode_image_grayscale_jpg_as_bgr():
    # NEU-DET 是灰度 jpg, 解码后必须是 3 通道(与 ultralytics 训练输入一致)
    gray = np.full((200, 200), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", gray)
    assert ok
    img = decode_image(buf.tobytes())
    assert img.ndim == 3
    assert img.shape == (200, 200, 3)


def test_decode_image_rejects_garbage():
    with pytest.raises(ValueError, match="无法解码"):
        decode_image(b"not an image at all")


def test_resolve_device_explicit_value_passthrough():
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("cuda:0") == "cuda:0"


@pytest.mark.parametrize("cuda_available", [True, False])
def test_resolve_device_auto(monkeypatch, cuda_available):
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: cuda_available)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    expected = "cuda:0" if cuda_available else "cpu"
    assert resolve_device("auto") == expected

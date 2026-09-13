"""阶段4 溯源模块单测

- 裁剪/padding/归一化/JPEG 编码等纯函数
- Milvus 过滤表达式构造(白名单防注入) 与 pk 规则
- ResNet50 用随机权重(weights=None)在 CPU 验证输出形状与归一化, 不下载 ImageNet 权重
"""
from __future__ import annotations

import numpy as np
import pytest

from app.trace import milvus_client
from app.trace.embedder import (
    ResNetEmbedder,
    crop_with_pad,
    l2_normalize,
    pad_bbox,
)
from app.trace.store import encode_crop_jpeg


# ---------- pad_bbox ----------

def test_pad_bbox_expands_by_ratio():
    # 100x100 的框在 300x300 图中央, 外扩 10% -> 120x120
    x1, y1, x2, y2 = pad_bbox(100, 100, 200, 200, 300, 300, pad_ratio=0.10)
    assert (x1, y1, x2, y2) == (90, 90, 210, 210)


def test_pad_bbox_clamps_to_image_border():
    # 贴左上角的小框外扩后不能越界
    x1, y1, x2, y2 = pad_bbox(0, 0, 20, 20, 200, 200, pad_ratio=0.5)
    assert x1 == 0 and y1 == 0
    assert x2 <= 200 and y2 <= 200
    assert x2 > x1 and y2 > y1


def test_pad_bbox_min_size_for_tiny_box():
    # 2x2 的碎框至少保底 16 边长
    x1, y1, x2, y2 = pad_bbox(100, 100, 102, 102, 400, 400, pad_ratio=0.0, min_size=16)
    assert x2 - x1 >= 16
    assert y2 - y1 >= 16


def test_pad_bbox_tiny_box_near_border_never_invalid():
    # 极小框紧贴右下边界也不能产出 x2<=x1 的非法裁剪
    x1, y1, x2, y2 = pad_bbox(197, 197, 199, 199, 200, 200, pad_ratio=0.5, min_size=16)
    assert 0 <= x1 < x2 <= 200
    assert 0 <= y1 < y2 <= 200


# ---------- crop / 归一化 / 编码 ----------

def test_crop_with_pad_shape_and_border():
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    crop = crop_with_pad(img, {"x1": 0, "y1": 0, "x2": 50, "y2": 60}, pad_ratio=0.2)
    assert crop.ndim == 3
    h, w = crop.shape[:2]
    assert w <= 200 and h <= 200
    assert w >= 50 and h >= 60  # 外扩后只可能更大(被边界截停)


def test_l2_normalize_unit_length():
    v = np.array([3.0, 4.0], dtype=np.float32)
    n = l2_normalize(v)
    assert np.isclose(np.linalg.norm(n), 1.0, atol=1e-6)
    np.testing.assert_allclose(n, [0.6, 0.8], atol=1e-6)


def test_l2_normalize_zero_vector_raises():
    with pytest.raises(ValueError):
        l2_normalize(np.zeros(4, dtype=np.float32))


def test_encode_crop_jpeg_decodable():
    crop = np.full((40, 60, 3), 128, dtype=np.uint8)
    data = encode_crop_jpeg(crop)
    assert data[:2] == b"\xff\xd8"  # JPEG 魔数
    decoded = __import__("cv2").imdecode(np.frombuffer(data, np.uint8), 1)
    assert decoded is not None
    assert decoded.shape[:2] == (40, 60)


# ---------- Milvus 表达式 / pk ----------

def test_build_pk_format():
    assert milvus_client.build_pk(123, 7) == "r123-7"


def test_build_expr_none():
    assert milvus_client._build_expr(None, None) is None


def test_build_expr_class_only():
    expr = milvus_client._build_expr("scratches", None)
    assert expr == 'class_name == "scratches"'


def test_build_expr_class_and_exclude():
    expr = milvus_client._build_expr("Crazing", 42)  # 大小写归一
    assert 'class_name == "crazing"' in expr
    assert "record_id != 42" in expr
    assert " and " in expr


def test_build_expr_rejects_unknown_class():
    with pytest.raises(ValueError):
        milvus_client._build_expr("drop table", None)


# ---------- ResNet50 输出契约(随机权重, 不下载) ----------

@pytest.fixture(scope="module")
def random_embedder():
    emb = ResNetEmbedder(device="cpu", weights=None)
    emb.load()
    return emb


def test_embedder_output_shape_and_norm(random_embedder):
    crops = [np.random.randint(0, 255, (70, 50, 3), dtype=np.uint8) for _ in range(3)]
    vecs = random_embedder.embed_crops(crops)
    assert vecs.shape == (3, 2048)
    assert vecs.dtype == np.float32
    norms = np.linalg.norm(vecs, axis=1)
    np.testing.assert_allclose(norms, np.ones(3), atol=1e-5)


def test_embedder_empty_input():
    emb = ResNetEmbedder(device="cpu", weights=None)
    out = emb.embed_crops([])
    assert out.shape == (0, 2048)


def test_embed_one_shape(random_embedder):
    v = random_embedder.embed_one(np.zeros((100, 100, 3), dtype=np.uint8))
    assert v.shape == (2048,)
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)

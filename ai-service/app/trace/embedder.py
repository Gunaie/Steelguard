"""缺陷裁剪图特征提取: ResNet50(ImageNet V2 权重) -> 2048 维 L2 归一化向量

设计要点:
- TORCH_HOME 重定向到项目内 .torch/, 权重不入 Git 也不污染用户目录
- 去掉最后的 fc 分类层, 取全局平均池化后的 2048 维语义特征(通用视觉表征)
- 预处理严格用权重自带 transforms(resize232/center224/ImageNet 归一化)
- device=auto 复用 YOLO 同款选择逻辑; 单例懒加载, 历史库批量入库只加载一次
- pad_bbox / l2_normalize 为纯函数, 独立单测
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

# 必须在 import torch/torchvision 前设置: 权重缓存到项目内目录
os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parents[2] / ".torch"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import settings  # noqa: E402

# ImageNet 归一化常量(transforms 内部也会用, 单测里直接对照)
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def pad_bbox(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
    pad_ratio: float = 0.08,
    min_size: int = 16,
) -> tuple[int, int, int, int]:
    """检测框外扩 pad_ratio 比例后裁剪到图像边界(纯函数)

    - 外扩可以把缺陷边缘上下文带入特征, 提升相似度稳定性
    - min_size: 贴边小框保底边长(像素), 避免裁剪图过小被 resize 后失真
    """
    bw, bh = x2 - x1, y2 - y1
    pad_x, pad_y = bw * pad_ratio, bh * pad_ratio
    cx1 = max(0, int(round(x1 - pad_x)))
    cy1 = max(0, int(round(y1 - pad_y)))
    cx2 = min(width, int(round(x2 + pad_x)))
    cy2 = min(height, int(round(y2 + pad_y)))
    # 保底边长: 以框中心向两边扩, 仍受图像边界约束
    if cx2 - cx1 < min_size:
        cx = int(round((x1 + x2) / 2))
        half = min_size // 2
        cx1 = max(0, cx - half)
        cx2 = min(width, cx + (min_size - half))
    if cy2 - cy1 < min_size:
        cy = int(round((y1 + y2) / 2))
        half = min_size // 2
        cy1 = max(0, cy - half)
        cy2 = min(height, cy + (min_size - half))
    return cx1, cy1, max(cx1 + 1, cx2), max(cy1 + 1, cy2)


def crop_with_pad(
    image: np.ndarray,
    bbox: dict[str, float],
    pad_ratio: float = 0.08,
    min_size: int = 16,
) -> np.ndarray:
    """按 bbox(像素坐标) 从 BGR 图像中裁剪缺陷区域"""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = pad_bbox(
        float(bbox["x1"]),
        float(bbox["y1"]),
        float(bbox["x2"]),
        float(bbox["y2"]),
        w,
        h,
        pad_ratio=pad_ratio,
        min_size=min_size,
    )
    return image[y1:y2, x1:x2].copy()


def l2_normalize(vector: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """L2 归一化(纯函数); 配合 COSINE/IP 度量, 使内积==余弦相似度"""
    norm = np.linalg.norm(vector)
    if norm < eps:
        raise ValueError("零向量无法归一化(特征提取异常)")
    return vector / norm


class ResNetEmbedder:
    """ResNet50 全局特征提取器(单例, 线程安全懒加载)"""

    def __init__(self, device: str = "auto", weights: Any = "DEFAULT") -> None:
        self._device_pref = device
        self._weights_arg = weights  # 测试可传 None(随机初始化, 不下载权重)
        self._model: Any = None
        self._transform: Any = None
        self._device: str | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str | None:
        return self._device

    def load(self) -> None:
        """加载权重并去掉 fc 层(双重检查锁, 多请求只加载一次)"""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import torch  # noqa: F401
            import torchvision
            from torchvision.models import ResNet50_Weights

            if self._weights_arg == "DEFAULT":
                weights = ResNet50_Weights.IMAGENET1K_V2
            else:
                weights = None  # None=随机权重(仅单测)
            model = torchvision.models.resnet50(weights=weights)
            model.fc = torch.nn.Identity()  # 去分类头: (N,2048) 池化特征
            model.eval()

            # auto: 有 CUDA 用 GPU(历史库批量入库快), 否则 CPU
            pref = (self._device_pref or settings.model_device or "auto").lower()
            if pref != "auto":
                self._device = pref
            else:
                self._device = "cuda:0" if torch.cuda.is_available() else "cpu"
            model.to(self._device)

            self._transform = (
                weights.transforms() if weights is not None else None
            )
            self._model = model

    def _build_batch_tensor(self, crops_bgr: list[np.ndarray]) -> Any:
        """BGR ndarray 列表 -> 预处理后的 batch tensor"""
        import torch
        from PIL import Image

        if self._transform is None:
            # 单测兜底: 手动 resize224 + ImageNet 归一化
            tensors = []
            for crop in crops_bgr:
                rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                resized = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_LINEAR)
                arr = resized.astype(np.float32) / 255.0
                # mean/std 必须同 float32, 否则 numpy 会把整张量提升为 float64
                arr = (arr - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(
                    IMAGENET_STD, dtype=np.float32
                )
                tensors.append(torch.from_numpy(arr.transpose(2, 0, 1)))
            return torch.stack(tensors)

        images = [Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)) for c in crops_bgr]
        return torch.stack([self._transform(img) for img in images])

    def embed_crops(
        self, crops_bgr: list[np.ndarray], batch_size: int = 32
    ) -> np.ndarray:
        """批量提取裁剪图特征, 返回 L2 归一化后的 (N, 2048) float32"""
        if not crops_bgr:
            return np.zeros((0, settings.embedding_dim), dtype=np.float32)
        self.load()
        import torch

        out: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(crops_bgr), batch_size):
                batch = crops_bgr[start : start + batch_size]
                tensor = self._build_batch_tensor(batch).to(self._device)
                feats = self._model(tensor).cpu().numpy().astype(np.float32)
                out.append(feats)
        vectors = np.concatenate(out, axis=0)
        # 逐行 L2 归一化
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        return vectors / norms

    def embed_one(self, crop_bgr: np.ndarray) -> np.ndarray:
        """单裁剪图 -> (2048,) 归一化向量"""
        return self.embed_crops([crop_bgr])[0]


# 全局单例
embedder = ResNetEmbedder()

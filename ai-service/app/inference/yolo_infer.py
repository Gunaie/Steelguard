"""YOLO 缺陷检测推理器

设计要点:
- 单例 + 懒加载(启动时预热), 模型只加载一次
- device=auto 时优先 CUDA; 加载即暴露 torch.cuda 状态, 杜绝"以为在用 GPU"
- 强制校验权重内类别顺序 == 训练导出顺序(字母序), 防止权重/代码类别错配
- 不调用 result.plot(), 不触发 Ultralytics 字体外网下载
- 纯函数 parse_detections 独立可单测
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

# 在 import ultralytics 前把其配置目录重定向到项目内, 避免写 %APPDATA%
# (部分 Windows 环境对 AppData 无写权限会刷 ERROR 噪声)
os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[2] / ".ultralytics"))

import cv2
import numpy as np

from app.config import settings

# 训练时 data.yaml 的类别顺序(字母序), 推理时必须严格对齐
YOLO_CLASSES: list[str] = [
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
]

CLASS_NAME_CN: dict[str, str] = {
    "crazing": "裂纹",
    "inclusion": "夹杂",
    "patches": "斑块",
    "pitted_surface": "麻点",
    "rolled-in_scale": "氧化铁皮",
    "scratches": "划痕",
}


def resolve_device(configured: str) -> str:
    """auto -> 有 CUDA 返回 cuda:0, 否则 cpu; 其它配置原样返回"""
    if configured and configured.lower() != "auto":
        return configured
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda:0"
    except ImportError:
        pass
    return "cpu"


def parse_detections(
    boxes: Any,
    names: dict[int, str],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """把 Ultralytics result.boxes 转成标准检测字典列表(纯函数, 便于单测)

    Args:
        boxes: ultralytics Results.boxes(有 xyxy/conf/cls, .cpu().numpy())
        names: 模型内 {class_id: class_name}
        width / height: 原图宽高(用于坐标截断保护)
    """
    if boxes is None or len(boxes) == 0:
        return []

    xyxy = boxes.xyxy.cpu().numpy()  # shape (N,4)
    confs = boxes.conf.cpu().numpy()  # shape (N,)
    clses = boxes.cls.cpu().numpy().astype(int)  # shape (N,)

    detections: list[dict[str, Any]] = []
    for (x1, y1, x2, y2), conf, cls_id in zip(xyxy, confs, clses, strict=True):
        class_name = names.get(int(cls_id), str(cls_id))
        # 数值保护: 截断到图像范围内, 并保证 x2>x1 / y2>y1
        x1 = max(0.0, min(float(x1), float(width)))
        y1 = max(0.0, min(float(y1), float(height)))
        x2 = max(0.0, min(float(x2), float(width)))
        y2 = max(0.0, min(float(y2), float(height)))
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            {
                "class_id": int(cls_id),
                "class_name": class_name,
                "class_name_cn": CLASS_NAME_CN.get(class_name, class_name),
                "confidence": round(float(conf), 4),
                "bbox": {
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                },
            }
        )
    # 置信度降序, 前端/下游直接可用
    detections.sort(key=lambda d: d["confidence"], reverse=True)
    return detections


def decode_image(image_bytes: bytes) -> np.ndarray:
    """图片字节 -> BGR ndarray (灰度 jpg 也按 3 通道解码, 与训练一致)"""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片, 请上传 jpg/png/webp 等常见格式")
    return img


class YoloInferencer:
    """YOLO 模型单例包装"""

    def __init__(self) -> None:
        self._model = None
        self._device: str | None = None
        self._names: dict[int, str] = {}
        self._lock = threading.Lock()
        self.load_error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str:
        return self._device or resolve_device(settings.model_device)

    @property
    def names(self) -> dict[int, str]:
        return self._names

    def load(self) -> None:
        """加载权重 + 校验类别 + GPU 预热"""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from ultralytics import YOLO

                device = resolve_device(settings.model_device)
                print(f"[YOLO] 加载权重: {settings.yolo_weights} (device={device})")
                model = YOLO(settings.yolo_weights)

                # 类别顺序强校验(权重内 names vs 训练约定)
                names = {int(k): str(v) for k, v in model.names.items()}
                actual = [names.get(i) for i in range(len(names))]
                if actual != YOLO_CLASSES:
                    raise RuntimeError(
                        f"权重类别顺序不匹配! 期望 {YOLO_CLASSES}, 实际 {actual}; "
                        "请确认 best.pt 来自 NEU-DET 训练且未换类序"
                    )

                # GPU 证据打印(版本 + 卡名), 避免静默回退 CPU
                if device.startswith("cuda"):
                    import torch

                    if not torch.cuda.is_available():
                        raise RuntimeError(
                            f"配置要求 {device} 但 torch.cuda.is_available()=False, "
                            "请检查 GPU 版 torch 与驱动"
                        )
                    print(
                        f"[YOLO] CUDA 可用: torch={torch.__version__}, "
                        f"gpu={torch.cuda.get_device_name(0)}"
                    )

                # 预热: 第一次推理会做 cudnn/算子初始化, 提前付出
                warm = np.zeros((settings.yolo_imgsz, settings.yolo_imgsz, 3), dtype=np.uint8)
                model.predict(
                    warm,
                    device=device,
                    imgsz=settings.yolo_imgsz,
                    verbose=False,
                )

                self._model = model
                self._device = device
                self._names = names
                self.load_error = None
                print(f"[YOLO] 模型就绪 ✓ device={device}, classes={names}")
            except Exception as exc:  # noqa: BLE001 - 服务启动不中断, 推理时明确报 503
                self.load_error = f"{type(exc).__name__}: {exc}"
                print(f"[YOLO] 模型加载失败: {self.load_error}")
                raise

    def predict(self, image_bytes: bytes, conf: float | None = None, iou: float | None = None) -> dict:
        """对图片字节做检测, 返回 DetectResponse 对应的 dict"""
        if self._model is None:
            self.load()
        if self._model is None:
            raise RuntimeError(f"YOLO 模型未就绪: {self.load_error}")

        img = decode_image(image_bytes)
        height, width = img.shape[:2]
        conf = conf if conf is not None else settings.yolo_conf
        iou = iou if iou is not None else settings.yolo_iou

        # 同卡串行推理, 避免多请求并发抢占显存/结果错乱
        with self._lock:
            t0 = time.perf_counter()
            results = self._model.predict(
                img,
                device=self._device,
                imgsz=settings.yolo_imgsz,
                conf=conf,
                iou=iou,
                verbose=False,
            )
            inference_ms = (time.perf_counter() - t0) * 1000

        result = results[0]
        detections = parse_detections(result.boxes, self._names, width, height)
        return {
            "model": settings.yolo_model_name,
            "device": self._device,
            "image_width": width,
            "image_height": height,
            "inference_ms": round(inference_ms, 2),
            "count": len(detections),
            "detections": detections,
        }


# 进程内单例
_inferencer: YoloInferencer | None = None
_inferencer_lock = threading.Lock()


def get_inferencer() -> YoloInferencer:
    global _inferencer
    # 双重检查锁, 避免并发重复加载
    if _inferencer is None:
        with _inferencer_lock:
            if _inferencer is None:
                _inferencer = YoloInferencer()
    return _inferencer

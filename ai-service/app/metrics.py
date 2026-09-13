"""阶段5.2 Prometheus 业务指标

HTTP 层 RED 指标(请求量/错误/延迟)由 prometheus-fastapi-instrumentator 自动
在 /metrics 暴露; 本模块只定义方案文档要求的 YOLO 业务指标:

- yolo_inference_duration_seconds: 单次检测端到端耗时(含锁排队/解码/推理),
  按 device/result 标签区分 —— 推理延迟
- yolo_detections_total: 检出缺陷框总数(按类别) —— 与 QPS 组合可看检测吞吐
- yolo_detection_confidence: 每个检出框的置信度分布直方图(按类别) —— 模型置信度分布
- yolo_model_info: 模型身份与加载状态(常量 1 的 Gauge, 标签承载信息)

设计: 指标全部进程内单例, Counter/Histogram 线程安全(prometheus_client 内部
带锁), 可在 FastAPI 线程池中并发观测。
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# 延迟桶: YOLO GPU 纯推理 ~12ms, 但高并发下含锁排队, 覆盖到 2s
_DURATION_BUCKETS = (
    0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05,
    0.075, 0.1, 0.15, 0.2, 0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0,
)
# 置信度桶: 阈值 0.25 起步, 细到 0.99
_CONFIDENCE_BUCKETS = (
    0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6,
    0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99,
)

INFERENCE_DURATION = Histogram(
    "yolo_inference_duration_seconds",
    "YOLO 单图检测端到端耗时(秒, 含解码/排队/GPU推理)",
    labelnames=("device", "result"),
    buckets=_DURATION_BUCKETS,
)

DETECTIONS_TOTAL = Counter(
    "yolo_detections_total",
    "YOLO 检出缺陷框总数",
    labelnames=("class_name",),
)

DETECTION_CONFIDENCE = Histogram(
    "yolo_detection_confidence",
    "YOLO 检出框置信度分布",
    labelnames=("class_name",),
    buckets=_CONFIDENCE_BUCKETS,
)

MODEL_INFO = Gauge(
    "yolo_model_info",
    "YOLO 模型信息(常量1; loaded=1 表示已加载, device/model 由标签承载)",
    labelnames=("model", "device", "loaded"),
)


def record_inference(device: str, seconds: float, detections: list[dict]) -> None:
    """成功检测的观测: 总耗时 + 每个框的类别计数与置信度"""
    INFERENCE_DURATION.labels(device=device, result="success").observe(seconds)
    for det in detections:
        class_name = str(det.get("class_name", "unknown"))
        confidence = float(det.get("confidence", 0.0))
        DETECTIONS_TOTAL.labels(class_name=class_name).inc()
        DETECTION_CONFIDENCE.labels(class_name=class_name).observe(confidence)


def record_inference_error(device: str, seconds: float) -> None:
    """失败检测的耗时(400 坏图/503 模型未就绪等), 便于发现错误延迟异常"""
    INFERENCE_DURATION.labels(device=device, result="error").observe(seconds)


def set_model_info(model: str, device: str, loaded: bool) -> None:
    """更新模型身份 Gauge(健康检查时调用)"""
    MODEL_INFO.labels(model=model, device=device, loaded="1" if loaded else "0").set(1)

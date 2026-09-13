"""推理接口的请求/响应模型"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """检测框, 像素绝对坐标(左上角 x1,y1 / 右下角 x2,y2)"""

    x1: float
    y1: float
    x2: float
    y2: float


class Detection(BaseModel):
    """单个缺陷检测结果"""

    class_id: int = Field(description="类别 id(0..5, 与训练字母序一致)")
    class_name: str = Field(description="类别英文名")
    class_name_cn: str = Field(description="类别中文名")
    confidence: float = Field(description="置信度 0..1")
    bbox: BBox


class DetectResponse(BaseModel):
    """YOLO 检测响应"""

    model: str = Field(description="模型标识, 如 yolo11s")
    device: str = Field(description="实际推理设备, 如 cuda:0 / cpu")
    image_width: int
    image_height: int
    inference_ms: float = Field(description="纯模型推理耗时(毫秒, 不含网络/解码)")
    count: int = Field(description="检出缺陷框总数")
    detections: list[Detection]


class DetectUrlRequest(BaseModel):
    """通过图片 URL 检测的请求体(批量对决时直接传 MinIO 预签名 URL)"""

    url: str = Field(description="可直接 GET 的图片 URL(http/https)")
    conf: float = Field(default=0.25, ge=0.01, le=1.0)
    iou: float = Field(default=0.7, ge=0.1, le=1.0)


class VlTokenUsage(BaseModel):
    """视觉大模型 token 用量(成本核算)"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class VlDetectResponse(BaseModel):
    """Qwen-VL 零样本检测响应(检测结构与 YOLO 对齐, 额外带 token/耗时用于对决)"""

    model: str = Field(description="实际调用的视觉模型 id")
    provider: str = Field(description="dashscope / ollama")
    image_width: int
    image_height: int
    inference_ms: float = Field(description="API 往返耗时(毫秒)")
    count: int
    detections: list[Detection]
    tokens: VlTokenUsage = Field(default_factory=VlTokenUsage)

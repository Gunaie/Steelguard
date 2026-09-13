"""溯源接口的请求/响应模型"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.inference.schemas import Detection


class IndexRequest(BaseModel):
    """缺陷案例入库请求(Java 批次编排时内部调用)

    图片直接走 MinIO(bucket+object), 不用预签名 URL:
    内部服务间调用更稳, 不存在签名过期问题。
    """

    record_id: int = Field(description="inspect_record 主键")
    batch_id: int = Field(description="所属 inspect_batch 主键")
    image_bucket: str = Field(description="原图所在 MinIO bucket")
    image_object: str = Field(description="原图 MinIO 对象路径")
    detections: list[Detection] = Field(default_factory=list, description="YOLO 检测框列表")


class IndexedCase(BaseModel):
    """单个入库案例回传(供 Java 侧计数/核对)"""

    milvus_pk: str
    class_name: str
    confidence: float
    crop_minio_path: str


class IndexResponse(BaseModel):
    record_id: int
    indexed: int = Field(description="入库缺陷案例数")
    embed_ms: float = Field(description="特征提取耗时(毫秒)")
    cases: list[IndexedCase] = Field(default_factory=list)


class SearchHit(BaseModel):
    """单条相似案例"""

    case_id: int
    milvus_pk: str
    score: float = Field(description="COSINE 相似度, 越接近 1 越相似")
    class_name: str
    class_name_cn: str = ""
    detect_confidence: float = Field(description="历史检测时的 YOLO 置信度")
    record_id: int
    batch_id: int
    batch_no: str
    batch_name: str | None = None
    image_name: str
    crop_url: str | None = Field(description="缺陷裁剪图预签名 URL")
    source_image_url: str | None = Field(description="历史原图预签名 URL")


class TraceSearchResponse(BaseModel):
    query_class: str | None = Field(description="检索时限定的类别(可空)")
    used_bbox: bool = Field(description="是否按指定框裁剪后检索")
    count: int
    total_cases: int = Field(description="向量库案例总数")
    embed_ms: float
    results: list[SearchHit] = Field(default_factory=list)


class TraceStats(BaseModel):
    collection: str
    total_cases: int
    by_class: dict[str, int]
    embedding_dim: int
    embedder_loaded: bool
    embedder_device: str | None = None

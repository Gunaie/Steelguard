"""阶段4.2 LLM 结构化质检报告的请求/响应模型

防幻觉的核心边界:
- ReportRequest 里全部是 Java 侧从 MySQL 聚合的"程序事实", 是报告唯一事实来源
- LLM 只产出 NarrativePart 里的文字结论, 不允许输出任何统计数字
- 最终报告 = 程序事实块(权威) + 相似案例块(检索证据) + LLM 叙述块(被校验)
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BatchFacts(BaseModel):
    """批次级程序事实(Java 聚合后注入, LLM 不得改写)"""

    batch_id: int
    batch_no: str
    name: str
    source: str = Field(description="dataset/upload/history")
    detect_model: str | None = Field(default=None, description="检测模型, 如 yolo11s")
    image_count: int = Field(ge=0)
    defect_image_count: int = Field(ge=0)
    defect_count: int = Field(ge=0, description="缺陷框总数")
    case_count: int = Field(ge=0, description="入向量库案例数")
    defect_rate: float = Field(ge=0, le=1, description="缺陷图占比 = 缺陷图数/总图数")
    box_density: float = Field(ge=0, description="框密度 = 缺陷框总数/总图数(数据集均值约2.33)")
    avg_inference_ms: float = Field(ge=0, description="单图平均检测耗时(毫秒)")
    high_risk_count: int = Field(ge=0, description="高危类(crazing+scratches)缺陷框数")
    rule_severity: str = Field(description="程序规则定级 low/medium/high/critical")


class ClassFact(BaseModel):
    """单类别程序事实(来源 defect_case 聚合)"""

    class_name: str
    class_name_cn: str
    count: int = Field(ge=0)
    ratio: float = Field(ge=0, le=1, description="该类占全部缺陷案例的比例")
    avg_confidence: float = Field(ge=0, le=1)


class RepresentativeCase(BaseModel):
    """批次内某类别最高置信代表案例(给 Milvus 做相似历史检索的锚点)"""

    class_name: str
    milvus_pk: str
    record_id: int


class ReportRequest(BaseModel):
    """Java -> Python 的报告生成请求(只含事实, 不含任何主观文字)"""

    batch: BatchFacts
    class_stats: list[ClassFact] = Field(default_factory=list)
    representatives: list[RepresentativeCase] = Field(
        default_factory=list,
        description="各类别代表案例 pk, 最多取前 3 类",
    )
    model: str | None = Field(default=None, description="覆盖默认 LLM 模型(可选)")


class SimilarCase(BaseModel):
    """相似历史案例(Milvus 检索 + MinIO 预签名, 全部可溯源)"""

    class_name: str
    class_name_cn: str = ""
    milvus_pk: str
    score: float = Field(description="COSINE 相似度")
    record_id: int
    batch_id: int
    batch_no: str
    image_name: str
    detect_confidence: float
    crop_url: str | None = None
    source_image_url: str | None = None


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ReportResponse(BaseModel):
    """报告生成响应: 最终自洽报告(程序事实+证据+叙述) + 调用元信息"""

    model: str
    provider: str
    latency_ms: float
    tokens: TokenUsage
    similar_cases: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] = Field(description="最终结构化报告, 直接落 inspect_batch.report_json")

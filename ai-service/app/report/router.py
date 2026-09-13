"""阶段4.2 结构化质检报告路由

POST /report/generate 内部接口(Java 网关 JWT 鉴权后调用):
  程序事实 -> Milvus 历史相似证据(best-effort) -> qwen-plus 叙述 -> 校验合并
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.report.builder import build_report
from app.report.llm_client import ReportError, report_llm
from app.report.schemas import ReportRequest, ReportResponse, TokenUsage
from app.report.similar import find_similar_cases

router = APIRouter(prefix="/report", tags=["质检报告"])

# ReportError.kind -> HTTP 状态码(与推理路由同一套语义)
REPORT_ERROR_STATUS = {
    "config": 503,
    "auth": 502,
    "ratelimit": 429,
    "timeout": 504,
    "upstream": 502,
    "badresponse": 502,
}


def _run_generate(req: ReportRequest) -> ReportResponse:
    # 1. 相似历史案例(检索证据): 基础设施抖动不阻断报告, 证据块降级为空
    similar_cases: list[dict] = []
    try:
        similar_cases = find_similar_cases(req.representatives, req.batch.batch_id)
    except Exception as exc:  # noqa: BLE001 - Milvus/MinIO/MySQL 任一不可用
        print(f"[report] 相似案例检索失败, 降级为空证据块: {exc}")

    # 2. LLM 叙述块(事实注入 + Schema 校验 + 修复重试)
    try:
        llm_result = report_llm.generate(
            facts=req.batch.model_dump(),
            class_stats=[c.model_dump() for c in req.class_stats],
            model=req.model,
        )
    except ReportError as exc:
        raise HTTPException(
            status_code=REPORT_ERROR_STATUS.get(exc.kind, 502), detail=str(exc)
        ) from exc

    # 3. 程序事实 + 检索证据 + LLM 叙述合并(数字永不经过模型)
    report = build_report(
        batch_facts=req.batch.model_dump(),
        class_stats=[c.model_dump() for c in req.class_stats],
        similar_cases=similar_cases,
        llm_result=llm_result,
    )
    return ReportResponse(
        model=llm_result["model"],
        provider=llm_result["provider"],
        latency_ms=llm_result["latency_ms"],
        tokens=TokenUsage(**llm_result["tokens"]),
        similar_cases=similar_cases,
        report=report,
    )


@router.post("/generate", response_model=ReportResponse, summary="生成批次结构化质检报告")
async def generate_report(req: ReportRequest) -> ReportResponse:
    """Java 聚合事实后调用; 阻塞型 LLM/Milvus 操作放线程池, 不卡事件循环"""
    return await run_in_threadpool(_run_generate, req)

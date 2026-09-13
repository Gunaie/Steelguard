"""推理路由: YOLO 本地检测 + Qwen-VL 零样本检测"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.config import settings
from app.inference.schemas import DetectResponse, DetectUrlRequest, VlDetectResponse
from app.inference.vl_infer import VlError, vl_detector
from app.inference.yolo_infer import get_inferencer

router = APIRouter(prefix="/infer", tags=["推理"])

# VlError.kind -> HTTP 状态码
VL_ERROR_STATUS = {
    "config": 503,
    "auth": 502,
    "ratelimit": 429,
    "timeout": 504,
    "upstream": 502,
    "badresponse": 502,
}


class DetectVlUrlRequest(BaseModel):
    """通过图片 URL 调视觉大模型(与 /detect-url 对称)"""

    url: str
    model: str | None = Field(default=None, description="plus / max / 具体模型 id; 空=配置选定")


def _run_detect(image_bytes: bytes, conf: float, iou: float) -> DetectResponse:
    """在线程池中执行阻塞式 torch 推理, 不卡 FastAPI 事件循环"""
    # 阶段5.2: 端到端埋点(含锁排队/解码/推理), 成功与失败分别记录
    import time  # noqa: PLC0415

    from app.metrics import record_inference, record_inference_error  # noqa: PLC0415

    t0 = time.perf_counter()
    try:
        result = get_inferencer().predict(image_bytes, conf=conf, iou=iou)
    except ValueError as exc:  # 图片解码失败
        record_inference_error(get_inferencer().device, time.perf_counter() - t0)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # 模型未就绪等
        record_inference_error(get_inferencer().device, time.perf_counter() - t0)
        raise HTTPException(status_code=503, detail=f"推理失败: {exc}") from exc
    record_inference(result["device"], time.perf_counter() - t0, result["detections"])
    return DetectResponse(**result)


@router.post("/detect", response_model=DetectResponse, summary="上传图片做缺陷检测")
async def detect(
    file: UploadFile = File(..., description="图片文件(jpg/png/webp)"),
    conf: float = Form(default=0.25, ge=0.01, le=1.0, description="置信度阈值"),
    iou: float = Form(default=0.7, ge=0.1, le=1.0, description="NMS IoU 阈值"),
) -> DetectResponse:
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(image_bytes) > settings.infer_max_image_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大: {len(image_bytes)} 字节, 上限 {settings.infer_max_image_bytes}",
        )
    return await run_in_threadpool(_run_detect, image_bytes, conf, iou)


@router.post("/detect-url", response_model=DetectResponse, summary="通过图片 URL 做缺陷检测")
async def detect_url(req: DetectUrlRequest) -> DetectResponse:
    if not req.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url 仅支持 http/https")

    # 流式拉取并限制大小, 防超大文件打爆内存
    chunks: list[bytes] = []
    total = 0
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            async with client.stream("GET", req.url) as resp:
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"下载图片失败: 上游 HTTP {resp.status_code}",
                    )
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > settings.infer_max_image_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"图片超过 {settings.infer_max_image_bytes} 字节上限",
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"下载图片出错: {exc}") from exc

    image_bytes = b"".join(chunks)
    return await run_in_threadpool(_run_detect, image_bytes, req.conf, req.iou)


# ---------------- Qwen-VL 零样本 ----------------

def _run_detect_vl(image_bytes: bytes, model: str | None) -> VlDetectResponse:
    try:
        result = vl_detector.detect_bytes(image_bytes, model=model)
    except ValueError as exc:  # 图片解码失败
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VlError as exc:
        raise HTTPException(
            status_code=VL_ERROR_STATUS.get(exc.kind, 502), detail=str(exc)
        ) from exc
    return VlDetectResponse(**result)


@router.post("/detect-vl", response_model=VlDetectResponse, summary="上传图片做 Qwen-VL 零样本检测")
async def detect_vl(
    file: UploadFile = File(..., description="图片文件(jpg/png/webp)"),
    model: str = Form(default="", description="plus / max / 具体模型 id; 空=配置选定"),
) -> VlDetectResponse:
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(image_bytes) > settings.infer_max_image_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大: {len(image_bytes)} 字节, 上限 {settings.infer_max_image_bytes}",
        )
    return await run_in_threadpool(_run_detect_vl, image_bytes, model or None)


@router.post("/detect-vl-url", response_model=VlDetectResponse, summary="通过 URL 做 Qwen-VL 零样本检测")
async def detect_vl_url(req: DetectVlUrlRequest) -> VlDetectResponse:
    if not req.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url 仅支持 http/https")

    chunks: list[bytes] = []
    total = 0
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            async with client.stream("GET", req.url) as resp:
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"下载图片失败: 上游 HTTP {resp.status_code}",
                    )
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > settings.infer_max_image_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"图片超过 {settings.infer_max_image_bytes} 字节上限",
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"下载图片出错: {exc}") from exc

    image_bytes = b"".join(chunks)
    return await run_in_threadpool(_run_detect_vl, image_bytes, req.model)

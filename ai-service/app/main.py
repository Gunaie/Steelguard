"""SteelGuard AI 推理服务入口

阶段0: 健康检查与 ping, 验证 Java->Python 链路。
阶段3: YOLO 缺陷检测(里程碑3.1) + Qwen-VL 零样本(里程碑3.2)。
"""
from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.inference.yolo_infer import get_inferencer


def _gpu_status() -> dict:
    """返回 CUDA 状态(健康检查用), torch 缺失也不报错"""
    status = {"cuda_available": False, "torch_version": None, "gpu_name": None}
    try:
        import torch

        status["torch_version"] = torch.__version__
        status["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            status["gpu_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        pass
    return status


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动: 在线程池中阻塞加载 YOLO(含 GPU 预热), 失败不阻断服务, 推理接口会明确报 503
    print(f"[{settings.app_name}] 启动中... port={settings.port}")
    inferencer = get_inferencer()
    try:
        await asyncio.to_thread(inferencer.load)
    except Exception as exc:  # noqa: BLE001
        print(f"[{settings.app_name}] 模型预热失败(服务仍启动, 推理将返回 503): {exc}")

    # 阶段4: ResNet50 溯源特征模型后台预热(不阻塞服务启动, 首次入库/检索不再等待)
    def _warmup_embedder() -> None:
        try:
            from app.trace.embedder import embedder as trace_embedder

            trace_embedder.load()
            print(
                f"[{settings.app_name}] 溯源 Embedding 预热完成 ✓ device={trace_embedder.device}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{settings.app_name}] Embedding 预热失败(首次溯源请求时将重试): {exc}")

    threading.Thread(target=_warmup_embedder, daemon=True).start()

    print(f"[{settings.app_name}] 启动完成 ✓")
    yield
    # 关闭
    print(f"[{settings.app_name}] 关闭中...")


app = FastAPI(
    title="SteelGuard AI Service",
    description="AI 服务: YOLO 缺陷检测 + Qwen-VL 零样本 + 缺陷相似溯源(Milvus) + LLM 结构化报告",
    version="0.4.2",
    lifespan=lifespan,
)

# CORS (允许 Java 后端调用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 阶段3 路由
from app.inference.router import router as inference_router  # noqa: E402
# 阶段4 路由
from app.trace.router import router as trace_router  # noqa: E402
# 阶段4.2 路由
from app.report.router import router as report_router  # noqa: E402

app.include_router(inference_router)
app.include_router(trace_router)
app.include_router(report_router)

# 阶段5.2: Prometheus 指标(/metrics; HTTP RED 自动采集, YOLO 业务指标见 app/metrics.py)
from prometheus_fastapi_instrumentator import Instrumentator  # noqa: E402

Instrumentator(
    should_group_status_codes=False,  # 状态码不合并(保留 200/400/503 细分, 便于排障)
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health", tags=["健康检查"])
async def health():
    """健康检查(含模型加载状态, 供排障与 Java 探活)"""
    inferencer = get_inferencer()
    gpu = _gpu_status()
    # 同步刷新 Prometheus 模型身份 Gauge(幂等, 同一标签集重复 set 无副作用)
    from app.metrics import set_model_info  # noqa: PLC0415

    set_model_info(settings.yolo_model_name, inferencer.device, inferencer.loaded)
    return {
        "service": settings.app_name,
        "status": "UP",
        "timestamp": int(time.time() * 1000),
        "model": {
            "name": settings.yolo_model_name,
            "weights": settings.yolo_weights,
            "loaded": inferencer.loaded,
            "device": inferencer.device,
            "configured_device": settings.model_device,
            "load_error": inferencer.load_error,
        },
        "gpu": gpu,
        "vl": {
            "provider": settings.vl_provider,
            "model": settings.vl_model,
            "model_plus": settings.vl_model_plus,
            "model_max": settings.vl_model_max,
            # 只暴露是否已配置, 绝不回显密钥
            "api_key_configured": bool(settings.dashscope_api_key),
        },
        "trace": {
            "collection": settings.milvus_collection,
            "milvus_endpoint": f"{settings.milvus_host}:{settings.milvus_port}",
            "embedding_dim": settings.embedding_dim,
        },
        "report_llm": {
            "provider": "dashscope",
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            # 只暴露是否已配置, 绝不回显密钥
            "api_key_configured": bool(settings.dashscope_api_key),
        },
    }


@app.get("/ping", tags=["探活"])
async def ping():
    """探活接口 (Java 推理网关调用验证)"""
    return {"message": "pong", "ai_service": settings.app_name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)

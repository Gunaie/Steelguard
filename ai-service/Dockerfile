# syntax=docker/dockerfile:1
# ==========================================================================
# SteelGuard AI 服务镜像(Python FastAPI) —— GPU/CPU 双模式共用一份 Dockerfile
#
# 构建方式(由 docker-compose 的 build args 注入, 也可手动):
#   GPU(默认, cu126 wheel):
#     docker build -t steelguard-ai:gpu .
#   CPU(纯 CPU wheel, 任意机器可跑, 无需 nvidia 容器运行时):
#     docker build --build-arg TORCH_INDEX_URL=https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels/cpu \
#                  -t steelguard-ai:cpu .
#
# 设计要点:
# - torch/torchvision 必须先于项目依赖安装(否则 ultralytics 拉依赖时可能把
#   cu126 版 torch 覆盖成 PyPI 默认版); 已装版本满足其版本约束, pip 不会重装
# - YOLO best.pt + ResNet50 .torch 权重烤入镜像, 运行时不依赖外网下载
# - 运行时不挂 GPU 也能启动(MODEL_DEVICE=auto 自动回退 CPU, 推理接口返回 503 前会先尝试)
# ==========================================================================
FROM python:3.12-slim-bookworm

# 国内镜像: torch 专用索引(默认 cu126; CPU 构建传 pytorch-wheels/cpu), 其余依赖走清华 PyPI
ARG TORCH_INDEX_URL=https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels/cu126
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# 与本机验证过的版本对齐(torch 2.14.0 + torchvision 0.29.0)
ARG TORCH_VERSION=2.14.0
ARG TORCHVISION_VERSION=0.29.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    TORCH_HOME=/app/.torch \
    YOLO_CONFIG_DIR=/app/.ultralytics

WORKDIR /app

# ultralytics -> opencv-python 运行时依赖 libGL/libglib; 换 Debian 清华源加速 apt
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 1) 先装 torch/torchvision(专用 wheel 索引: cu126 或 cpu)
RUN pip install \
        --index-url "${TORCH_INDEX_URL}" \
        --extra-index-url "${PIP_INDEX_URL}" \
        "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}"

# 2) 再装项目自身与其余依赖(走清华 PyPI; torch 已满足 ultralytics 约束, 不会被覆盖)
COPY pyproject.toml ./
COPY app ./app
RUN pip install --index-url "${PIP_INDEX_URL}" .

# 构建期留痕: 确认最终 torch 版本/变体(GPU 镜像在无 GPU 的构建机上 cuda False 属正常,
# wheel 内已含 CUDA 运行库, 运行环境给 --gpus all 即可用)
RUN python -c "import torch, torchvision; print('[build] torch', torch.__version__, 'torchvision', torchvision.__version__)"

# 3) 模型权重与 ResNet50 缓存(best.pt 18MB / best.onnx 36MB / resnet50 98MB)
COPY weights ./weights
COPY .torch ./.torch
RUN mkdir -p /app/.ultralytics

# 非 root 运行
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8001

# 模型预热 + ResNet 加载可能耗时, 给足启动宽限
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=5).status == 200 else 1)"

# 容器内关闭 --reload(代码以镜像形式发布)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]

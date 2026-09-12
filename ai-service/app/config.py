"""SteelGuard AI 服务配置"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 服务
    app_name: str = "steelguard-ai-service"
    host: str = "0.0.0.0"
    port: int = 8001

    # CORS
    backend_origin: str = "http://localhost:8080"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    # 对外端点: 仅用于生成预签名 URL(浏览器需可达; 容器内 I/O 走 minio:9000,
    # 预签名走 host.docker.internal:9000)。留空时回退 minio_endpoint(宿主开发零影响)
    minio_public_endpoint: str = ""
    minio_access_key: str = "steelguard"
    minio_secret_key: str = "steelguard123"
    minio_bucket: str = "datasets"
    minio_secure: bool = False

    # MySQL (数据集元数据)
    mysql_host: str = "localhost"
    mysql_port: int = 4406
    mysql_database: str = "steelguard"
    mysql_user: str = "root"
    mysql_password: str = "steelguard123"

    # 数据集路径(项目根目录下的 data/raw/NEU-DET)
    dataset_root: str = "data/raw/NEU-DET"
    dataset_images_dir: str = "IMAGES"
    dataset_annotations_dir: str = "ANNOTATIONS"
    dataset_minio_prefix: str = "neu-det/raw"
    dataset_augment_prefix: str = "neu-det/augmented"

    # 阶段3: YOLO 推理
    yolo_weights: str = "weights/best.pt"
    yolo_model_name: str = "yolo11s"
    # auto=有 CUDA 用 GPU 否则 CPU; 也可显式写 cuda:0 / cpu
    model_device: str = "auto"
    yolo_imgsz: int = 224
    yolo_conf: float = 0.25
    yolo_iou: float = 0.7
    # 远程拉取图片(URL 推理/批量对决)大小上限 10MB
    infer_max_image_bytes: int = 10 * 1024 * 1024

    # 阶段3.2: Qwen-VL 零样本检测
    # provider=dashscope(阿里云百炼, OpenAI 兼容) / ollama(本地兜底)
    vl_provider: str = "dashscope"
    dashscope_api_key: str = ""
    vl_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 两档候选 + 最终选定模型(pilot 对比后写入 VL_MODEL)
    vl_model_plus: str = "qwen-vl-plus"
    vl_model_max: str = "qwen-vl-max"
    vl_model: str = "qwen-vl-plus"
    vl_timeout: float = 60.0
    # Ollama 本地兜底
    ollama_base_url: str = "http://localhost:11434/v1"
    vl_model_ollama: str = "qwen2.5vl:7b"

    # 阶段4: Milvus 缺陷相似检索
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "defect_cases"
    embedding_dim: int = 2048  # ResNet50 avgpool 输出维度
    search_default_topk: int = 8
    # 缺陷裁剪图存放(检测现场图也存这个 bucket 的 inspect/ 前缀)
    defect_bucket: str = "defect-images"
    crop_prefix: str = "crops"
    inspect_prefix: str = "inspect"

    # 阶段4.2: LLM 结构化报告(百炼文本模型, 复用 DASHSCOPE_API_KEY)
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    llm_timeout: float = 90.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

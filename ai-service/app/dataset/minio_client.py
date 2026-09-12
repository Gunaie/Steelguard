"""MinIO 客户端: 上传/下载/预签名 URL"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Union

from minio import Minio
from minio.error import S3Error

from app.config import settings


def get_minio_client() -> Minio:
    """创建 MinIO 客户端(内部端点, 用于实际上传/下载 I/O)"""
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def get_presign_client() -> Minio:
    """创建预签名专用客户端(对外端点, 仅离线签名不产生网络流量)

    容器部署时内部 I/O 端点(minio:9000)浏览器不可达,
    预签名必须使用宿主可达端点(host.docker.internal:9000 / 宿主 IP)。
    未配置对外端点时回退内部端点, 与宿主开发环境行为一致。
    """
    endpoint = settings.minio_public_endpoint or settings.minio_endpoint
    # minio-py 构造器会强制在 endpoint 前再拼一次 scheme,
    # 传入带 http(s):// 的完整 URL 会变成 http://http://host 并报
    # "path in endpoint is not allowed", 这里先剥协议头并据此推导 secure。
    secure = endpoint.startswith("https://")
    host = (
        endpoint.removeprefix("https://")
        .removeprefix("http://")
        .rstrip("/")
    )
    return Minio(
        host,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    """确保 bucket 存在"""
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"[MinIO] 创建 bucket: {bucket}")
    else:
        print(f"[MinIO] bucket 已存在: {bucket}")


def upload_file(
    client: Minio,
    bucket: str,
    object_path: str,
    file_path: str | Path,
    content_type: str = "application/octet-stream",
) -> str:
    """上传文件到 MinIO

    Args:
        client: MinIO 客户端
        bucket: bucket 名
        object_path: 对象路径(如 neu-det/raw/crazing_1.jpg)
        file_path: 本地文件路径
        content_type: MIME 类型

    Returns:
        object_path 上传后的对象路径
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    client.fput_object(
        bucket_name=bucket,
        object_name=object_path,
        file_path=str(file_path),
        content_type=content_type,
    )
    return object_path


def presigned_url(
    client: Minio,
    bucket: str,
    object_path: str,
    expires: Union[int, timedelta] = 3600,
) -> Optional[str]:
    """生成预签名下载 URL

    Args:
        client: MinIO 客户端
        bucket: bucket 名
        object_path: 对象路径
        expires: 过期时间, 接受秒数(int, 默认 1 小时)或 timedelta

    Returns:
        预签名 URL, 失败返回 None
    """
    if isinstance(expires, int):
        expires = timedelta(seconds=expires)
    try:
        return client.presigned_get_object(
            bucket_name=bucket,
            object_name=object_path,
            expires=expires,
        )
    except S3Error as e:
        print(f"[MinIO] 预签名失败 {object_path}: {e}")
        return None

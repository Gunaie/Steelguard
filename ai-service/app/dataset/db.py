"""MySQL 数据库连接(轻量 pymysql 直连)

阶段1 不引入 ORM, 直接 pymysql 操作 dataset_* 三张表
"""
from __future__ import annotations

import pymysql
from pymysql.cursors import Cursor

from app.config import settings


def get_connection() -> pymysql.connections.Connection:
    """获取 MySQL 连接"""
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset="utf8mb4",
        autocommit=False,
    )


def create_version(
    conn: pymysql.connections.Connection,
    version: str,
    dataset_name: str,
    source: str,
    image_count: int,
    annotation_count: int,
    augment_factor: int,
    total_count: int,
    status: str = "draft",
    remark: str | None = None,
) -> int:
    """创建数据集版本记录, 返回 version_id"""
    with conn.cursor() as cur:  # type: Cursor
        cur.execute(
            """INSERT INTO dataset_version
               (version, dataset_name, source, image_count, annotation_count,
                augment_factor, total_count, status, remark)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (version, dataset_name, source, image_count, annotation_count,
             augment_factor, total_count, status, remark),
        )
    conn.commit()
    # 获取自增 ID
    with conn.cursor() as cur:  # type: Cursor
        cur.execute("SELECT LAST_INSERT_ID()")
        return cur.fetchone()[0]


def insert_image(
    conn: pymysql.connections.Connection,
    version_id: int,
    file_name: str,
    class_name: str,
    width: int,
    height: int,
    depth: int,
    file_size: int,
    minio_path: str,
    split: str = "raw",
    source_image_id: int | None = None,
    augment_method: str | None = None,
) -> int:
    """插入图片记录, 返回 image_id"""
    with conn.cursor() as cur:  # type: Cursor
        cur.execute(
            """INSERT INTO dataset_image
               (version_id, file_name, class_name, width, height, depth,
                file_size, minio_path, split, source_image_id, augment_method)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (version_id, file_name, class_name, width, height, depth,
             file_size, minio_path, split, source_image_id, augment_method),
        )
    # 不在这里 commit, 由调用方批量提交
    with conn.cursor() as cur:  # type: Cursor
        cur.execute("SELECT LAST_INSERT_ID()")
        return cur.fetchone()[0]


def insert_annotation(
    conn: pymysql.connections.Connection,
    image_id: int,
    class_name: str,
    xmin: int,
    ymin: int,
    xmax: int,
    ymax: int,
) -> None:
    """插入标注框记录"""
    with conn.cursor() as cur:  # type: Cursor
        cur.execute(
            """INSERT INTO dataset_annotation
               (image_id, class_name, xmin, ymin, xmax, ymax)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (image_id, class_name, xmin, ymin, xmax, ymax),
        )


def get_eda_stats(conn: pymysql.connections.Connection, version_id: int) -> dict:
    """查询指定版本的 EDA 统计"""
    with conn.cursor(pymysql.cursors.DictCursor) as cur:  # type: Cursor
        # 类别分布
        cur.execute(
            """SELECT class_name,
                      COUNT(DISTINCT id) AS image_count,
                      SUM(0) AS placeholder
               FROM dataset_image
               WHERE version_id=%s AND deleted=0
               GROUP BY class_name
               ORDER BY class_name""",
            (version_id,),
        )
        rows = cur.fetchall()
        class_dist = []
        for r in rows:
            cur.execute(
                """SELECT COUNT(*) AS bbox_count
                   FROM dataset_annotation a
                   JOIN dataset_image i ON a.image_id=i.id
                   WHERE i.version_id=%s AND a.class_name=%s""",
                (version_id, r["class_name"]),
            )
            bbox_count = cur.fetchone()["bbox_count"]
            class_dist.append({
                "class_name": r["class_name"],
                "image_count": r["image_count"],
                "bbox_count": bbox_count,
            })

        # 框数分布
        cur.execute(
            """SELECT bbox_cnt, COUNT(*) AS image_count
               FROM (
                   SELECT i.id, COUNT(a.id) AS bbox_cnt
                   FROM dataset_image i
                   LEFT JOIN dataset_annotation a ON a.image_id=i.id
                   WHERE i.version_id=%s AND i.deleted=0
                   GROUP BY i.id
               ) t
               GROUP BY bbox_cnt
               ORDER BY bbox_cnt""",
            (version_id,),
        )
        bbox_per_image = cur.fetchall()

        # 总数
        cur.execute(
            """SELECT
                 (SELECT COUNT(*) FROM dataset_image WHERE version_id=%s AND deleted=0) AS total_images,
                 (SELECT COUNT(*) FROM dataset_annotation a JOIN dataset_image i ON a.image_id=i.id
                  WHERE i.version_id=%s AND i.deleted=0) AS total_bboxes""",
            (version_id, version_id),
        )
        totals = cur.fetchone()

    return {
        "total_images": totals["total_images"],
        "total_annotations": totals["total_bboxes"],
        "class_distribution": class_dist,
        "bbox_per_image_distribution": bbox_per_image,
    }

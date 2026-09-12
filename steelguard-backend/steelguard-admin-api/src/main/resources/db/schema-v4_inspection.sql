-- SteelGuard 质检批次 + 缺陷溯源建表脚本（阶段4 / 里程碑4.1）
-- 三张表: inspect_batch(质检批次) / inspect_record(单图检测记录) / defect_case(缺陷案例, Milvus 关系镜像)
-- 用法: Get-Content schema-v4_inspection.sql -Raw -Encoding UTF8 |
--       docker exec -i steelguard-mysql mysql -uroot -psteelguard123 --default-character-set=utf8mb4 steelguard

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- 质检批次表: 一次批量质检 = 一个批次(数据集抽样/现场上传/历史基线)
-- ----------------------------
DROP TABLE IF EXISTS `inspect_batch`;
CREATE TABLE `inspect_batch` (
    `id`                  BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `batch_no`            VARCHAR(64)  NOT NULL COMMENT '批次号(业务唯一, 如 BATCH-20260913-001/HIST-NEUDET-RAW)',
    `name`                VARCHAR(128) NOT NULL COMMENT '批次名称',
    `source`              VARCHAR(16)  NOT NULL DEFAULT 'dataset' COMMENT 'dataset=数据集抽样 upload=现场上传 history=历史基线',
    `status`              VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending/detecting/done/failed',
    `model`               VARCHAR(32)           DEFAULT NULL COMMENT '检测模型(如 yolo11s)',
    `image_count`         INT          NOT NULL DEFAULT 0 COMMENT '批次图片数',
    `processed_count`     INT          NOT NULL DEFAULT 0 COMMENT '已处理图片数(跑批进度, 前端轮询)',
    `defect_image_count`  INT          NOT NULL DEFAULT 0 COMMENT '检出缺陷的图片数',
    `defect_count`        INT          NOT NULL DEFAULT 0 COMMENT '缺陷框总数',
    `case_count`          INT          NOT NULL DEFAULT 0 COMMENT '入向量库的缺陷案例数',
    `severity`            VARCHAR(16)           DEFAULT NULL COMMENT '程序规则定级 low/medium/high/critical(4.2 LLM 复核)',
    `total_inference_ms`  DOUBLE       NOT NULL DEFAULT 0 COMMENT 'YOLO 纯推理累计耗时(毫秒)',
    `error_msg`           VARCHAR(500)          DEFAULT NULL COMMENT '跑批中的部分失败信息(不中断整批)',
    `report_json`         LONGTEXT              DEFAULT NULL COMMENT '4.2 LLM 结构化质检报告 JSON',
    `report_model`        VARCHAR(64)           DEFAULT NULL COMMENT '报告生成模型',
    `llm_tokens`          INT                   DEFAULT NULL COMMENT '报告 LLM token 用量',
    `reported`            TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已生成 LLM 报告',
    `created_by`          BIGINT                DEFAULT NULL COMMENT '创建人 sys_user.id(历史基线为空)',
    `deleted`             TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除',
    `create_time`         DATETIME              DEFAULT CURRENT_TIMESTAMP,
    `update_time`         DATETIME              DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_batch_no` (`batch_no`),
    KEY `idx_status` (`status`),
    KEY `idx_source` (`source`),
    KEY `idx_create_time` (`create_time`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '质检批次表';

-- ----------------------------
-- 单图检测记录表: 每张受检图一行, 检测框 JSON 原样留存
-- ----------------------------
DROP TABLE IF EXISTS `inspect_record`;
CREATE TABLE `inspect_record` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `batch_id`      BIGINT       NOT NULL COMMENT '所属批次ID',
    `image_name`    VARCHAR(255) NOT NULL COMMENT '图片名(数据集文件名/上传原名)',
    `width`         INT                   DEFAULT NULL COMMENT '图宽',
    `height`        INT                   DEFAULT NULL COMMENT '图高',
    `minio_bucket`  VARCHAR(64)           DEFAULT NULL COMMENT '原图所在 MinIO bucket',
    `minio_path`    VARCHAR(255)          DEFAULT NULL COMMENT '原图 MinIO 对象路径',
    `model`         VARCHAR(32)           DEFAULT NULL COMMENT '检测模型',
    `inference_ms`  DOUBLE                DEFAULT NULL COMMENT '该图 YOLO 推理耗时(毫秒)',
    `det_count`     INT          NOT NULL DEFAULT 0 COMMENT '检出框数',
    `result_json`   TEXT                  DEFAULT NULL COMMENT '检测响应 detections 原文 JSON',
    `source_ref`    VARCHAR(128)          DEFAULT NULL COMMENT 'dataset 来源的 dataset_image.id, upload 为空',
    `create_time`   DATETIME              DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_batch` (`batch_id`),
    KEY `idx_name` (`image_name`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '单图检测记录表';

-- ----------------------------
-- 缺陷案例表: 每个检测框一行, Milvus 向量库的关系镜像
-- (相似度/pk 来自 Milvus, 业务元数据/裁剪图路径/统计走 MySQL)
-- ----------------------------
DROP TABLE IF EXISTS `defect_case`;
CREATE TABLE `defect_case` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `record_id`       BIGINT       NOT NULL COMMENT '来源检测记录ID',
    `batch_id`        BIGINT       NOT NULL COMMENT '来源批次ID',
    `class_name`      VARCHAR(64)  NOT NULL COMMENT '缺陷类别(6类英文标识)',
    `confidence`      DOUBLE       NOT NULL DEFAULT 0 COMMENT 'YOLO 检测置信度',
    `x1`              DOUBLE                DEFAULT NULL COMMENT '框坐标(像素)',
    `y1`              DOUBLE                DEFAULT NULL,
    `x2`              DOUBLE                DEFAULT NULL,
    `y2`              DOUBLE                DEFAULT NULL,
    `crop_minio_path` VARCHAR(255) NOT NULL COMMENT '缺陷裁剪图 MinIO 路径(defect-images/crops/...)',
    `milvus_pk`       VARCHAR(128) NOT NULL COMMENT 'Milvus 主键 r{record_id}-{box_index}',
    `create_time`     DATETIME              DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_milvus_pk` (`milvus_pk`),
    KEY `idx_record` (`record_id`),
    KEY `idx_batch` (`batch_id`),
    KEY `idx_class` (`class_name`),
    KEY `idx_create_time` (`create_time`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '缺陷案例表(Milvus 关系镜像)';

SET FOREIGN_KEY_CHECKS = 1;

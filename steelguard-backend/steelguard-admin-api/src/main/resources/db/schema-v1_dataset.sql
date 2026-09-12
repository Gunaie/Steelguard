-- SteelGuard 数据集工程建表脚本（阶段1）
-- 三张表: dataset_version / dataset_image / dataset_annotation
-- 用法: docker exec -i steelguard-mysql mysql -uroot -psteelguard123 steelguard < schema-v1_dataset.sql

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- 数据集版本表：记录每次导入/增强产生的版本
-- ----------------------------
DROP TABLE IF EXISTS `dataset_version`;
CREATE TABLE `dataset_version` (
    `id`               BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `version`          VARCHAR(32)  NOT NULL COMMENT '版本号(如 v1-raw, v1-aug5)',
    `dataset_name`     VARCHAR(64)  NOT NULL DEFAULT 'NEU-DET' COMMENT '数据集名称',
    `source`           VARCHAR(128)          DEFAULT 'NEU(Northeastern University)' COMMENT '来源',
    `image_count`      INT          NOT NULL DEFAULT 0 COMMENT '原始图片数',
    `annotation_count` INT          NOT NULL DEFAULT 0 COMMENT '标注框总数',
    `augment_factor`   INT          NOT NULL DEFAULT 1 COMMENT '增强倍数(1=无增强,5=原图+4增强)',
    `total_count`      INT          NOT NULL DEFAULT 0 COMMENT '入库总图片数(原始×倍数)',
    `status`           VARCHAR(16)           DEFAULT 'draft' COMMENT 'draft/importing/ready/archived',
    `remark`           VARCHAR(255)          DEFAULT NULL COMMENT '备注',
    `create_time`      DATETIME              DEFAULT CURRENT_TIMESTAMP,
    `update_time`      DATETIME              DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_version` (`version`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '数据集版本表';

-- ----------------------------
-- 数据集图片表：1800 原始 + 7200 增强 = 9000 行
-- ----------------------------
DROP TABLE IF EXISTS `dataset_image`;
CREATE TABLE `dataset_image` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `version_id`      BIGINT       NOT NULL COMMENT '所属版本ID',
    `file_name`       VARCHAR(128) NOT NULL COMMENT '文件名(增强图含后缀)',
    `class_name`      VARCHAR(64)  NOT NULL COMMENT '缺陷类别(6类之一)',
    `width`           INT          NOT NULL COMMENT '图像宽度',
    `height`          INT          NOT NULL COMMENT '图像高度',
    `depth`           INT          NOT NULL DEFAULT 1 COMMENT '通道数(灰度=1)',
    `file_size`       BIGINT                DEFAULT 0 COMMENT '文件大小(字节)',
    `minio_path`      VARCHAR(255)          DEFAULT NULL COMMENT 'MinIO 对象路径',
    `split`           VARCHAR(16)  NOT NULL DEFAULT 'raw' COMMENT 'raw=原始, augmented=增强',
    `source_image_id` BIGINT                DEFAULT NULL COMMENT '增强图来源原图ID(raw为空)',
    `augment_method`  VARCHAR(64)           DEFAULT NULL COMMENT '增强方法(horizontal_flip/vertical_flip/rotate/brightness/gaussian_noise)',
    `deleted`         TINYINT               DEFAULT 0 COMMENT '逻辑删除',
    `create_time`     DATETIME              DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_version` (`version_id`),
    KEY `idx_class` (`class_name`),
    KEY `idx_split` (`split`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '数据集图片表';

-- ----------------------------
-- 数据集标注表：每图可多框
-- ----------------------------
DROP TABLE IF EXISTS `dataset_annotation`;
CREATE TABLE `dataset_annotation` (
    `id`         BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `image_id`   BIGINT       NOT NULL COMMENT '所属图片ID',
    `class_name` VARCHAR(64)  NOT NULL COMMENT '缺陷类别',
    `xmin`       INT          NOT NULL COMMENT 'VOC绝对像素 xmin',
    `ymin`       INT          NOT NULL COMMENT 'VOC绝对像素 ymin',
    `xmax`       INT          NOT NULL COMMENT 'VOC绝对像素 xmax',
    `ymax`       INT          NOT NULL COMMENT 'VOC绝对像素 ymax',
    `create_time` DATETIME             DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_image` (`image_id`),
    KEY `idx_class` (`class_name`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '数据集标注表';

SET FOREIGN_KEY_CHECKS = 1;

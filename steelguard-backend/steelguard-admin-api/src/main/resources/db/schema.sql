-- SteelGuard 数据库初始化脚本
-- 阶段0: 仅建 sys_user 表 + 兜底管理员
-- 后续阶段按需追加表

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- 用户表
-- ----------------------------
DROP TABLE IF EXISTS `sys_user`;
CREATE TABLE `sys_user` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `username`    VARCHAR(64)  NOT NULL COMMENT '用户名',
    `password`    VARCHAR(128) NOT NULL COMMENT '密码(BCrypt)',
    `nickname`    VARCHAR(64)           DEFAULT NULL COMMENT '昵称',
    `role`        VARCHAR(32)           DEFAULT 'user' COMMENT '角色',
    `status`      TINYINT               DEFAULT 1 COMMENT '状态: 1启用 0禁用',
    `deleted`     TINYINT               DEFAULT 0 COMMENT '逻辑删除',
    `create_time` DATETIME             DEFAULT CURRENT_TIMESTAMP,
    `update_time` DATETIME             DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`, `deleted`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '用户表';

SET FOREIGN_KEY_CHECKS = 1;

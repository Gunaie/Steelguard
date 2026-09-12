-- SteelGuard 全新库初始化: 兜底管理员
-- 仅在 MySQL 数据卷为空(首次初始化)时由 /docker-entrypoint-initdb.d 执行
-- 默认口令 admin123(BCrypt), 登录后请修改; 与手工部署环境保持一致
USE `steelguard`;

INSERT INTO `sys_user` (`username`, `password`, `nickname`, `role`, `status`)
VALUES ('admin',
        '$2a$10$yDbXQ34y0wGC5noVMIkLWuNlRihMNOjOAP0fWqzRNHRPM8AZcC532',
        '系统管理员',
        'admin',
        1);

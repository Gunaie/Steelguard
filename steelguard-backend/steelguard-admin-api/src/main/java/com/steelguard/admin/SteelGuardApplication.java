package com.steelguard.admin;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * SteelGuard 启动类
 */
@SpringBootApplication(scanBasePackages = {"com.steelguard.admin", "com.steelguard.common"})
@MapperScan("com.steelguard.admin.**.mapper")
public class SteelGuardApplication {

    public static void main(String[] args) {
        SpringApplication.run(SteelGuardApplication.class, args);
        System.out.println("\n" +
                "========================================\n" +
                "  SteelGuard Admin API 启动成功\n" +
                "  Swagger: http://localhost:8080/api/doc.html\n" +
                "========================================\n");
    }
}

package com.steelguard.admin.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.Components;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * SpringDoc / Knife4j 接口文档配置
 */
@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI steelguardOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("SteelGuard Admin API")
                        .description("AI 钢材表面缺陷智能质检平台 - 后台管理接口")
                        .version("0.1.0")
                        .contact(new Contact().name("SteelGuard")))
                // 全局 JWT 鉴权按钮
                .components(new Components()
                        .addSecuritySchemes("Bearer-JWT",
                                new SecurityScheme()
                                        .type(SecurityScheme.Type.HTTP)
                                        .scheme("bearer")
                                        .bearerFormat("JWT")))
                .addSecurityItem(new SecurityRequirement().addList("Bearer-JWT"));
    }
}

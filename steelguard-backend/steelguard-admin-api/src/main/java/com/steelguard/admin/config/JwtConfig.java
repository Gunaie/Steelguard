package com.steelguard.admin.config;

import com.steelguard.common.jwt.JwtUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * JWT 配置
 */
@Configuration
public class JwtConfig {

    @Value("${steelguard.jwt.secret}")
    private String secret;

    @Value("${steelguard.jwt.expire}")
    private long expire;

    @Bean
    public JwtUtils jwtUtils() {
        return new JwtUtils(secret, expire);
    }
}

package com.steelguard.admin.security;

import com.steelguard.common.jwt.JwtUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.Duration;

/**
 * JWT 登出黑名单(Redis)
 *
 * 设计:
 * - key = steelguard:jwt:blacklist:{jti}, value 固定 "1"
 * - TTL = token 剩余有效期, token 自然过期后黑名单条目自动清理, 不产生长期垃圾
 * - JWT 本身无状态无法主动失效, 黑名单是服务端撤销通道;
 *   JwtAuthFilter 每请求校验 jti 是否在黑名单中
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TokenBlacklistService {

    public static final String KEY_PREFIX = "steelguard:jwt:blacklist:";

    private final StringRedisTemplate redisTemplate;
    private final JwtUtils jwtUtils;

    /** 登出: 把 token 的 jti 写入黑名单, TTL 取 token 剩余寿命 */
    public void blacklist(String token) {
        if (!StringUtils.hasText(token)) {
            return;
        }
        // 先算剩余寿命(内部对过期 token 容错); 已过期/已失效则无需落黑名单
        long remainingMillis;
        String jti;
        try {
            remainingMillis = jwtUtils.getRemainingMillis(token);
            if (remainingMillis <= 0) {
                return;
            }
            jti = jwtUtils.getId(token);
        } catch (Exception e) {
            // 非法/无法解析的 token 登出直接幂等成功, 不让接口 500
            log.debug("登出 token 解析失败, 跳过黑名单: {}", e.getMessage());
            return;
        }
        if (!StringUtils.hasText(jti)) {
            log.warn("登出的 token 缺少 jti 声明, 无法加入黑名单");
            return;
        }
        redisTemplate.opsForValue().set(
                KEY_PREFIX + jti, "1", Duration.ofMillis(remainingMillis));
    }

    /** jti 是否在黑名单中; jti 为空(历史 token 兼容)放行, 交由过期时间兜底 */
    public boolean isBlacklisted(String jti) {
        if (!StringUtils.hasText(jti)) {
            return false;
        }
        return Boolean.TRUE.equals(redisTemplate.hasKey(KEY_PREFIX + jti));
    }
}

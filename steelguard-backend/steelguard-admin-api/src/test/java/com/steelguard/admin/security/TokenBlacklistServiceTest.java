package com.steelguard.admin.security;

import com.steelguard.common.jwt.JwtUtils;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 登出黑名单服务测试: 验证 Redis key 规则与 TTL=token 剩余有效期
 */
@ExtendWith(MockitoExtension.class)
class TokenBlacklistServiceTest {

    private static final String SECRET =
            "steelguard-jwt-secret-for-unit-test-2026-09-13-0123456789";

    @Mock
    private StringRedisTemplate redisTemplate;
    @Mock
    private ValueOperations<String, String> valueOps;

    private JwtUtils jwtUtils;
    private TokenBlacklistService blacklistService;

    @BeforeEach
    void setUp() {
        jwtUtils = new JwtUtils(SECRET, 86_400_000L);
        blacklistService = new TokenBlacklistService(redisTemplate, jwtUtils);
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOps);
    }

    @Test
    void blacklistWritesJtiWithRemainingTtl() {
        String token = jwtUtils.generate("1", Map.of("username", "admin"));
        String jti = jwtUtils.getId(token);

        blacklistService.blacklist(token);

        ArgumentCaptor<Duration> ttl = ArgumentCaptor.forClass(Duration.class);
        verify(valueOps).set(eq(TokenBlacklistService.KEY_PREFIX + jti), eq("1"), ttl.capture());
        assertFalse(ttl.getValue().isZero());
        assertTrue(ttl.getValue().compareTo(Duration.ofHours(24)) <= 0);
    }

    @Test
    void expiredTokenIsNotWrittenToBlacklist() throws InterruptedException {
        JwtUtils shortLived = new JwtUtils(SECRET, 1L);
        String token = shortLived.generate("1", Map.of());
        Thread.sleep(50L);

        blacklistService.blacklist(token);

        verifyNoInteractions(valueOps);
    }

    @Test
    void emptyTokenIsNoop() {
        blacklistService.blacklist("");
        verifyNoInteractions(valueOps);
    }

    @Test
    void isBlacklistedReadsRedis() {
        when(redisTemplate.hasKey(TokenBlacklistService.KEY_PREFIX + "jti-1")).thenReturn(true);
        when(redisTemplate.hasKey(TokenBlacklistService.KEY_PREFIX + "jti-2")).thenReturn(false);

        assertTrue(blacklistService.isBlacklisted("jti-1"));
        assertFalse(blacklistService.isBlacklisted("jti-2"));
    }

    @Test
    void blankJtiPassesThroughForBackwardCompatibility() {
        // 无 jti 的历史 token 无法撤销, 视为"不在黑名单"放行, 由过期时间兜底
        assertFalse(blacklistService.isBlacklisted(null));
        assertFalse(blacklistService.isBlacklisted(""));
        verify(redisTemplate, never()).hasKey(anyString());
    }
}

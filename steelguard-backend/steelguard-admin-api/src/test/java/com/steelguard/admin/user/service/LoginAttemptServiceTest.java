package com.steelguard.admin.user.service;

import com.steelguard.common.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 登录失败计数(Redis)测试
 */
@ExtendWith(MockitoExtension.class)
class LoginAttemptServiceTest {

    private static final String KEY = LoginAttemptService.KEY_PREFIX + "admin";

    @Mock
    private StringRedisTemplate redisTemplate;
    @Mock
    private ValueOperations<String, String> valueOps;

    private LoginAttemptService loginAttemptService;

    @BeforeEach
    void setUp() {
        loginAttemptService = new LoginAttemptService(redisTemplate);
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOps);
    }

    @Test
    void noRecordMeansNotLocked() {
        when(valueOps.get(KEY)).thenReturn(null);
        assertDoesNotThrow(() -> loginAttemptService.assertNotLocked("admin"));
    }

    @Test
    void fourFailuresStillAllowed() {
        when(valueOps.get(KEY)).thenReturn("4");
        assertDoesNotThrow(() -> loginAttemptService.assertNotLocked("admin"));
    }

    @Test
    void fiveFailuresLocksAccount() {
        when(valueOps.get(KEY)).thenReturn("5");
        BusinessException ex = assertThrows(BusinessException.class,
                () -> loginAttemptService.assertNotLocked("admin"));
        assertEquals(423, ex.getCode());
    }

    @Test
    void firstFailureStartsExpireWindow() {
        when(valueOps.increment(KEY)).thenReturn(1L);
        loginAttemptService.recordFailure("admin");
        verify(redisTemplate).expire(KEY, Duration.ofMinutes(15));
    }

    @Test
    void subsequentFailuresDoNotResetExpire() {
        when(valueOps.increment(KEY)).thenReturn(3L);
        loginAttemptService.recordFailure("admin");
        verify(redisTemplate, never()).expire(anyString(), any(Duration.class));
    }

    @Test
    void successfulLoginClearsCounter() {
        loginAttemptService.reset("admin");
        verify(redisTemplate).delete(KEY);
    }
}

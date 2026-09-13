package com.steelguard.admin.user.service;

import com.steelguard.common.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;

/**
 * 登录失败计数(Redis)
 *
 * 防爆破策略:
 * - 同一用户名连续密码错误 5 次 -> 锁定 15 分钟, 锁定期间直接拒绝登录
 * - key 首次写入时设置过期, 窗口结束自动解锁, 无需定时任务
 * - 登录成功立即清零
 * 注意计数维度是用户名而非 IP: 本系统部署于内网质检工位, 用户名维度更能
 * 直接防护针对 admin 的撞库; 公网化时应再叠加 IP 维度限流。
 */
@Service
@RequiredArgsConstructor
public class LoginAttemptService {

    public static final String KEY_PREFIX = "steelguard:login:fail:";
    public static final int MAX_ATTEMPTS = 5;
    public static final Duration LOCK_WINDOW = Duration.ofMinutes(15);

    private final StringRedisTemplate redisTemplate;

    /** 登录前校验: 失败次数已达上限则拒绝 */
    public void assertNotLocked(String username) {
        String value = redisTemplate.opsForValue().get(KEY_PREFIX + username);
        if (value != null && Integer.parseInt(value) >= MAX_ATTEMPTS) {
            throw new BusinessException(423,
                    "密码连续错误 " + MAX_ATTEMPTS + " 次, 账号已锁定, 请 "
                            + LOCK_WINDOW.toMinutes() + " 分钟后再试");
        }
    }

    /** 记录一次密码错误; 窗口内第一次失败时启动 15 分钟过期计时 */
    public void recordFailure(String username) {
        Long count = redisTemplate.opsForValue().increment(KEY_PREFIX + username);
        if (count != null && count == 1L) {
            redisTemplate.expire(KEY_PREFIX + username, LOCK_WINDOW);
        }
    }

    /** 登录成功后清除失败计数 */
    public void reset(String username) {
        redisTemplate.delete(KEY_PREFIX + username);
    }
}

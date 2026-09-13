package com.steelguard.common.jwt;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * JWT 签发/解析/过期/jti 测试(无 Spring 上下文)
 */
class JwtUtilsTest {

    /** HMAC-SHA256 要求 >=32 字节密钥 */
    private static final String SECRET =
            "steelguard-jwt-secret-for-unit-test-2026-09-13-0123456789";

    private JwtUtils jwt(long expireMillis) {
        return new JwtUtils(SECRET, expireMillis);
    }

    @Test
    void generateAndParseRoundtrip() {
        JwtUtils jwt = jwt(86_400_000L);
        String token = jwt.generate("42", Map.of("username", "admin"));

        Claims claims = jwt.parse(token);
        assertEquals("42", claims.getSubject());
        assertEquals("admin", claims.get("username"));
        assertTrue(jwt.isValid(token));
    }

    @Test
    void eachTokenHasUniqueJti() {
        JwtUtils jwt = jwt(86_400_000L);
        String t1 = jwt.generate("1", Map.of());
        String t2 = jwt.generate("1", Map.of());
        assertNotNull(jwt.getId(t1));
        assertNotEquals(jwt.getId(t1), jwt.getId(t2), "jti 必须全局唯一, 登出黑名单依赖它");
    }

    @Test
    void tamperedOrMalformedTokenInvalid() {
        JwtUtils jwt = jwt(86_400_000L);
        String token = jwt.generate("1", Map.of());

        // 交换 payload 段前两个字符: 可正常 base64 解码但内容已变, HMAC 签名必然失配
        // (注意: 不能只在 token 末尾追加非法字符, jjwt 的 Base64 解码器会静默丢弃)
        String[] parts = token.split("\\.");
        String payload = parts[1];
        char c0 = payload.charAt(0);
        char c1 = payload.charAt(1);
        assertNotEquals(c0, c1, "前置假设: payload 前两字符不同");
        String swapped = c1 + "" + c0 + payload.substring(2);
        String tampered = parts[0] + "." + swapped + "." + parts[2];

        assertFalse(jwt.isValid(tampered));
        assertFalse(jwt.isValid("not-a-jwt"));
        assertThrows(JwtException.class, () -> jwt.parse(tampered));
    }

    @Test
    void differentSecretRejectsToken() {
        String token = jwt(86_400_000L).generate("1", Map.of());
        JwtUtils other = new JwtUtils(
                "another-secret-key-another-secret-key-0123456789-abcd", 86_400_000L);
        assertFalse(other.isValid(token));
    }

    @Test
    void expiredTokenInvalid() throws InterruptedException {
        JwtUtils jwt = jwt(1L);
        String token = jwt.generate("1", Map.of());
        Thread.sleep(50L);
        assertFalse(jwt.isValid(token));
        assertEquals(0L, jwt.getRemainingMillis(token), "已过期 token 剩余寿命应为 0");
    }

    @Test
    void remainingMillisBoundedByExpire() {
        long expire = 60_000L;
        JwtUtils jwt = jwt(expire);
        String token = jwt.generate("1", Map.of());
        long remaining = jwt.getRemainingMillis(token);
        assertTrue(remaining > 0 && remaining <= expire);
    }
}

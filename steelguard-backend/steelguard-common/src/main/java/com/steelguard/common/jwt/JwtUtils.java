package com.steelguard.common.jwt;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.Map;
import java.util.UUID;

/**
 * JWT 工具类
 * - 签发的每个 token 带唯一 jti, 供 Redis 登出黑名单按 jti 撤销
 * - 无状态解析/校验保留在本类, 有状态的撤销判断放在 TokenBlacklistService
 */
public class JwtUtils {

    private final SecretKey key;
    private final long expireMillis;

    public JwtUtils(String secret, long expireMillis) {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expireMillis = expireMillis;
    }

    /** 生成 token */
    public String generate(String subject, Map<String, Object> claims) {
        Date now = new Date();
        Date exp = new Date(now.getTime() + expireMillis);
        return Jwts.builder()
                .id(UUID.randomUUID().toString())
                .subject(subject)
                .claims(claims)
                .issuedAt(now)
                .expiration(exp)
                .signWith(key)
                .compact();
    }

    /** 解析 token */
    public Claims parse(String token) {
        return Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    /** 校验 token 是否有效 */
    public boolean isValid(String token) {
        try {
            parse(token);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 从 token 取 userId(Subject) */
    public String getSubject(String token) {
        return parse(token).getSubject();
    }

    /** 从 token 取 jti(唯一标识, 登出黑名单用) */
    public String getId(String token) {
        return parse(token).getId();
    }

    /**
     * token 剩余有效毫秒(登出写入黑名单时作为 Redis TTL),
     * 已过期或无 exp 声明返回 0。
     * 过期 token 解析会抛 ExpiredJwtException, 但其 claims 中仍带 exp, 需容错取出。
     */
    public long getRemainingMillis(String token) {
        Date exp;
        try {
            exp = parse(token).getExpiration();
        } catch (io.jsonwebtoken.ExpiredJwtException e) {
            exp = e.getClaims().getExpiration();
        }
        if (exp == null) {
            return 0L;
        }
        return Math.max(0L, exp.getTime() - System.currentTimeMillis());
    }
}

package com.steelguard.admin.security;

import com.steelguard.common.constant.SecurityConstant;
import com.steelguard.common.jwt.JwtUtils;
import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Collections;
import java.util.List;

/**
 * JWT 鉴权过滤器
 */
@Component
@RequiredArgsConstructor
public class JwtAuthFilter extends OncePerRequestFilter {

    private final JwtUtils jwtUtils;
    private final TokenBlacklistService tokenBlacklistService;
    private final JwtAuthEntryPoint jwtAuthEntryPoint;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String header = request.getHeader(SecurityConstant.AUTH_HEADER);
        String token = null;
        if (StringUtils.hasText(header) && header.startsWith(SecurityConstant.TOKEN_PREFIX)) {
            token = header.substring(SecurityConstant.TOKEN_PREFIX.length());
        }

        if (StringUtils.hasText(token) && jwtUtils.isValid(token)) {
            Claims claims = jwtUtils.parse(token);
            // 登出黑名单: jti 已被撤销则拒绝, 走统一 401 入口
            if (tokenBlacklistService.isBlacklisted(claims.getId())) {
                SecurityContextHolder.clearContext();
                jwtAuthEntryPoint.commence(request, response,
                        new BadCredentialsException("token 已注销"));
                return;
            }
            String userId = claims.getSubject();
            String username = String.valueOf(claims.get(SecurityConstant.USERNAME_KEY));

            // 构造认证信息
            List<SimpleGrantedAuthority> authorities = Collections.singletonList(new SimpleGrantedAuthority("ROLE_USER"));
            LoginUser loginUser = new LoginUser(Long.valueOf(userId), username);
            UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(loginUser, null, authorities);
            SecurityContextHolder.getContext().setAuthentication(auth);
        }

        chain.doFilter(request, response);
    }
}

package com.steelguard.admin.user.controller;

import com.steelguard.admin.security.TokenBlacklistService;
import com.steelguard.admin.user.dto.LoginRequest;
import com.steelguard.admin.user.dto.LoginResponse;
import com.steelguard.admin.user.dto.RegisterRequest;
import com.steelguard.admin.user.service.UserService;
import com.steelguard.common.constant.SecurityConstant;
import com.steelguard.common.result.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "认证")
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class AuthController {

    private final UserService userService;
    private final TokenBlacklistService tokenBlacklistService;

    @Operation(summary = "登录")
    @PostMapping("/login")
    public Result<LoginResponse> login(@Valid @RequestBody LoginRequest req) {
        return Result.ok(userService.login(req));
    }

    @Operation(summary = "登出(当前 token 加入 Redis 黑名单, TTL=剩余有效期)")
    @PostMapping("/logout")
    public Result<Void> logout(HttpServletRequest request) {
        String header = request.getHeader(SecurityConstant.AUTH_HEADER);
        if (StringUtils.hasText(header) && header.startsWith(SecurityConstant.TOKEN_PREFIX)) {
            tokenBlacklistService.blacklist(header.substring(SecurityConstant.TOKEN_PREFIX.length()));
        }
        return Result.ok();
    }

    @Operation(summary = "注册")
    @PostMapping("/register")
    public Result<Long> register(@Valid @RequestBody RegisterRequest req) {
        return Result.ok(userService.register(req));
    }
}

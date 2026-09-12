package com.steelguard.admin.user.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.steelguard.admin.user.dto.LoginRequest;
import com.steelguard.admin.user.dto.LoginResponse;
import com.steelguard.admin.user.dto.RegisterRequest;
import com.steelguard.admin.user.entity.User;
import com.steelguard.admin.user.mapper.UserMapper;
import com.steelguard.common.exception.BusinessException;
import com.steelguard.common.jwt.JwtUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;

/**
 * 用户服务: 登录/注册
 * 阶段0: 用 DB 用户; 如库为空则用内置 admin/steel123 兜底账号
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserService {

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtils jwtUtils;

    // 兜底账号(库为空时使用)
    private static final String FALLBACK_USERNAME = "admin";
    private static final String FALLBACK_PASSWORD = "steel123";

    public LoginResponse login(LoginRequest req) {
        String username = req.getUsername();
        String password = req.getPassword();

        // 1. 查库
        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, username)
        );

        if (user == null) {
            // 2. 库无此用户 -> 尝试兜底账号
            if (FALLBACK_USERNAME.equals(username) && FALLBACK_PASSWORD.equals(password)) {
                // 自动注册 admin 到库
                user = initFallbackUser();
            } else {
                throw new BusinessException(400, "用户名或密码错误");
            }
        } else {
            // 校验密码
            if (!passwordEncoder.matches(password, user.getPassword())) {
                throw new BusinessException(400, "用户名或密码错误");
            }
            if (user.getStatus() != null && user.getStatus() == 0) {
                throw new BusinessException(403, "账号已被禁用");
            }
        }

        // 生成 token
        Map<String, Object> claims = new HashMap<>();
        claims.put("userId", user.getId());
        claims.put("username", user.getUsername());
        String token = jwtUtils.generate(String.valueOf(user.getId()), claims);

        return LoginResponse.builder()
                .token(token)
                .tokenType("Bearer")
                .userId(user.getId())
                .username(user.getUsername())
                .nickname(user.getNickname())
                .role(user.getRole())
                .build();
    }

    public Long register(RegisterRequest req) {
        Long exist = userMapper.selectCount(
                new LambdaQueryWrapper<User>().eq(User::getUsername, req.getUsername())
        );
        if (exist != null && exist > 0) {
            throw new BusinessException(400, "用户名已存在");
        }
        User user = new User();
        user.setUsername(req.getUsername());
        user.setPassword(passwordEncoder.encode(req.getPassword()));
        user.setNickname(req.getNickname() == null ? req.getUsername() : req.getNickname());
        user.setRole("user");
        user.setStatus(1);
        userMapper.insert(user);
        return user.getId();
    }

    /** 初始化兜底管理员 */
    private User initFallbackUser() {
        User user = new User();
        user.setUsername(FALLBACK_USERNAME);
        user.setPassword(passwordEncoder.encode(FALLBACK_PASSWORD));
        user.setNickname("系统管理员");
        user.setRole("admin");
        user.setStatus(1);
        userMapper.insert(user);
        log.info("初始化兜底管理员账号: admin");
        return user;
    }
}

package com.steelguard.admin.user.service;

import com.steelguard.admin.user.dto.LoginRequest;
import com.steelguard.admin.user.dto.LoginResponse;
import com.steelguard.admin.user.entity.User;
import com.steelguard.admin.user.mapper.UserMapper;
import com.steelguard.common.exception.BusinessException;
import com.steelguard.common.jwt.JwtUtils;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 登录业务测试: 失败计数联动 / 锁定短路 / 兜底管理员
 */
@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    @Mock
    private UserMapper userMapper;
    @Mock
    private PasswordEncoder passwordEncoder;
    @Mock
    private JwtUtils jwtUtils;
    @Mock
    private LoginAttemptService loginAttemptService;

    private UserService userService;

    @BeforeEach
    void setUp() {
        userService = new UserService(userMapper, passwordEncoder, jwtUtils, loginAttemptService);
    }

    private LoginRequest req(String username, String password) {
        LoginRequest r = new LoginRequest();
        r.setUsername(username);
        r.setPassword(password);
        return r;
    }

    private User dbUser(long id, String username, String encodedPwd, Integer status) {
        User u = new User();
        u.setId(id);
        u.setUsername(username);
        u.setPassword(encodedPwd);
        u.setStatus(status);
        u.setRole("admin");
        u.setNickname("管理员");
        return u;
    }

    @Test
    void lockedAccountIsRejectedBeforeDbQuery() {
        doThrow(new BusinessException(423, "账号已锁定"))
                .when(loginAttemptService).assertNotLocked("admin");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> userService.login(req("admin", "whatever")));
        assertEquals(423, ex.getCode());
        verify(userMapper, never()).selectOne(any());
        verify(jwtUtils, never()).generate(anyString(), anyMap());
    }

    @Test
    void wrongPasswordRecordsFailureAndRejects() {
        when(userMapper.selectOne(any())).thenReturn(dbUser(1L, "admin", "hash", 1));
        when(passwordEncoder.matches("bad", "hash")).thenReturn(false);

        assertThrows(BusinessException.class, () -> userService.login(req("admin", "bad")));
        verify(loginAttemptService).recordFailure("admin");
        verify(loginAttemptService, never()).reset(anyString());
        verify(jwtUtils, never()).generate(anyString(), anyMap());
    }

    @Test
    void successResetsCounterAndIssuesToken() {
        when(userMapper.selectOne(any())).thenReturn(dbUser(1L, "admin", "hash", 1));
        when(passwordEncoder.matches("ok", "hash")).thenReturn(true);
        when(jwtUtils.generate(eq("1"), any(Map.class))).thenReturn("token-1");

        LoginResponse resp = userService.login(req("admin", "ok"));

        assertEquals("token-1", resp.getToken());
        assertEquals(1L, resp.getUserId());
        verify(loginAttemptService).reset("admin");
        verify(loginAttemptService, never()).recordFailure(anyString());
    }

    @Test
    void disabledAccountRejected() {
        when(userMapper.selectOne(any())).thenReturn(dbUser(1L, "admin", "hash", 0));
        when(passwordEncoder.matches(anyString(), anyString())).thenReturn(true);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> userService.login(req("admin", "ok")));
        assertEquals(403, ex.getCode());
        // 密码正确但账号禁用, 不记失败
        verify(loginAttemptService, never()).recordFailure(anyString());
    }

    @Test
    void unknownUserFallbackBootstrapsAdmin() {
        when(userMapper.selectOne(any())).thenReturn(null);
        when(passwordEncoder.encode("steel123")).thenReturn("encoded");
        when(jwtUtils.generate(anyString(), anyMap())).thenReturn("boot-token");
        // insert 回填自增 id
        doAnswer(inv -> {
            ((User) inv.getArgument(0)).setId(99L);
            return 1;
        }).when(userMapper).insert(any(User.class));

        LoginResponse resp = userService.login(req("admin", "steel123"));

        assertEquals("boot-token", resp.getToken());
        assertEquals(99L, resp.getUserId());
        verify(userMapper).insert(any(User.class));
        verify(loginAttemptService).reset("admin");
    }

    @Test
    void unknownUserWithWrongPasswordRecordsFailure() {
        when(userMapper.selectOne(any())).thenReturn(null);

        assertThrows(BusinessException.class,
                () -> userService.login(req("admin", "wrong")));
        verify(loginAttemptService).recordFailure("admin");
        verify(userMapper, never()).insert(any(User.class));
    }
}

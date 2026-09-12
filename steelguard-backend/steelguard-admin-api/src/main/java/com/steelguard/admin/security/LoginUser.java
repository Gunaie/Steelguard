package com.steelguard.admin.security;

import lombok.AllArgsConstructor;
import lombok.Data;

/**
 * 登录用户上下文(放 SecurityContextHolder)
 */
@Data
@AllArgsConstructor
public class LoginUser {
    private Long userId;
    private String username;
}

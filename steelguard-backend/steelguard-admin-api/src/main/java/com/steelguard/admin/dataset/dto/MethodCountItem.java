package com.steelguard.admin.dataset.dto;

import lombok.Data;

/**
 * 增强方法分布项
 */
@Data
public class MethodCountItem {

    /** raw 时为 null */
    private String augmentMethod;

    private Long imageCount;
}

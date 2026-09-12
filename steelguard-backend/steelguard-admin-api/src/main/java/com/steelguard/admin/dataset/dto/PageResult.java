package com.steelguard.admin.dataset.dto;

import lombok.Data;

import java.util.List;

/**
 * 简单分页结果
 */
@Data
public class PageResult<T> {

    private Long total;

    private Long page;

    private Long size;

    private List<T> list;

    public PageResult(Long total, Long page, Long size, List<T> list) {
        this.total = total;
        this.page = page;
        this.size = size;
        this.list = list;
    }
}

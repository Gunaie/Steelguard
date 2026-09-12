package com.steelguard.admin.dataset.dto;

import lombok.Data;

/**
 * 类别分布项: 每类图片数 + 标注框数
 */
@Data
public class ClassCountItem {

    private String className;

    private Long imageCount;

    private Long bboxCount;
}

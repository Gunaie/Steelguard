package com.steelguard.admin.dataset.dto;

import lombok.Data;

/**
 * 每图框数分布项: bboxCount 个框的图片有 imageCount 张
 */
@Data
public class BboxCountItem {

    private Integer bboxCount;

    private Long imageCount;
}

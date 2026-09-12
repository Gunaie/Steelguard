package com.steelguard.admin.dataset.dto;

import lombok.Data;

/**
 * 数据集图片项(含 MinIO 预签名访问 URL)
 */
@Data
public class DatasetImageVO {

    private Long id;

    private String fileName;

    private String className;

    private Integer width;

    private Integer height;

    private String split;

    private String augmentMethod;

    private Long fileSize;

    /** MinIO 预签名 GET URL(1 小时有效) */
    private String url;
}

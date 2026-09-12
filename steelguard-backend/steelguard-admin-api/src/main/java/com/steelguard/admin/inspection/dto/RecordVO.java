package com.steelguard.admin.inspection.dto;

import lombok.Data;

/**
 * 批次详情中的单图检测记录(带原图预签名 URL)
 */
@Data
public class RecordVO {

    private Long id;
    private String imageName;
    private Integer width;
    private Integer height;
    private String model;
    private Double inferenceMs;
    private Integer detCount;
    /** 检测框 JSON 原文(前端画框直接用) */
    private String resultJson;
    private String url;
}

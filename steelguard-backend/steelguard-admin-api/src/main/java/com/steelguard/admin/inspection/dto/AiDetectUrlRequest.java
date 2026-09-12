package com.steelguard.admin.inspection.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

/**
 * 调 Python /infer/detect-url 的请求体
 */
@Data
@AllArgsConstructor
public class AiDetectUrlRequest {

    private String url;
    private Double conf;
    private Double iou;
}

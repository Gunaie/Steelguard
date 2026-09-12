package com.steelguard.admin.inspection.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.steelguard.admin.inference.dto.Detection;
import lombok.Data;

import java.util.List;

/**
 * 调 Python /trace/index 的请求体: 一张图的检测框入向量库
 * (字段名与 Python pydantic 模型严格对齐 snake_case)
 */
@Data
public class AiTraceIndexRequest {

    @JsonProperty("record_id")
    private Long recordId;

    @JsonProperty("batch_id")
    private Long batchId;

    @JsonProperty("image_bucket")
    private String imageBucket;

    @JsonProperty("image_object")
    private String imageObject;

    private List<Detection> detections;
}

package com.steelguard.admin.inspection.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * Python /trace/index 响应
 */
@Data
public class AiTraceIndexResponse {

    @JsonProperty("record_id")
    private Long recordId;

    private Integer indexed;

    @JsonProperty("embed_ms")
    private Double embedMs;

    private List<CaseItem> cases;

    @Data
    public static class CaseItem {
        @JsonProperty("milvus_pk")
        private String milvusPk;
        @JsonProperty("class_name")
        private String className;
        private Double confidence;
        @JsonProperty("crop_minio_path")
        private String cropMinioPath;
    }
}

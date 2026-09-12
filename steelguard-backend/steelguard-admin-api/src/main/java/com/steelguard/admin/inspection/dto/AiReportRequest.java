package com.steelguard.admin.inspection.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * 调 Python /report/generate 的请求体(4.2 结构化质检报告)。
 * 全部是 Java 从 MySQL 聚合的"程序事实", 是报告唯一可信数据源; LLM 只写文字。
 * 字段名与 Python pydantic ReportRequest 严格对齐 snake_case。
 */
@Data
public class AiReportRequest {

    private BatchFacts batch;

    @JsonProperty("class_stats")
    private List<ClassFact> classStats;

    private List<RepresentativeCase> representatives;

    /** 覆盖默认 LLM 模型(可选, 一般传 null) */
    private String model;

    @Data
    public static class BatchFacts {
        @JsonProperty("batch_id")
        private Long batchId;

        @JsonProperty("batch_no")
        private String batchNo;

        private String name;

        private String source;

        @JsonProperty("detect_model")
        private String detectModel;

        @JsonProperty("image_count")
        private Integer imageCount;

        @JsonProperty("defect_image_count")
        private Integer defectImageCount;

        @JsonProperty("defect_count")
        private Integer defectCount;

        @JsonProperty("case_count")
        private Integer caseCount;

        @JsonProperty("defect_rate")
        private Double defectRate;

        @JsonProperty("box_density")
        private Double boxDensity;

        @JsonProperty("avg_inference_ms")
        private Double avgInferenceMs;

        @JsonProperty("high_risk_count")
        private Integer highRiskCount;

        @JsonProperty("rule_severity")
        private String ruleSeverity;
    }

    @Data
    public static class ClassFact {
        @JsonProperty("class_name")
        private String className;

        @JsonProperty("class_name_cn")
        private String classNameCn;

        private Integer count;

        private Double ratio;

        @JsonProperty("avg_confidence")
        private Double avgConfidence;
    }

    @Data
    public static class RepresentativeCase {
        @JsonProperty("class_name")
        private String className;

        @JsonProperty("milvus_pk")
        private String milvusPk;

        @JsonProperty("record_id")
        private Long recordId;
    }
}

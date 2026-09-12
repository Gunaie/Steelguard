package com.steelguard.admin.inspection.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * Python /report/generate 响应(4.2)。
 * report 是最终自洽报告(程序事实+证据+LLM 叙述), 直接落 inspect_batch.report_json。
 * similar_cases 是带预签名 URL 的历史相似案例(供前端展示)。
 */
@Data
public class AiReportResponse {

    private String model;

    private String provider;

    @JsonProperty("latency_ms")
    private Double latencyMs;

    private TokenUsage tokens;

    @JsonProperty("similar_cases")
    private List<Map<String, Object>> similarCases;

    /** 最终结构化报告(原样 JSON 字符串落库) */
    private Map<String, Object> report;

    @Data
    public static class TokenUsage {
        @JsonProperty("prompt_tokens")
        private Integer promptTokens;

        @JsonProperty("completion_tokens")
        private Integer completionTokens;

        @JsonProperty("total_tokens")
        private Integer totalTokens;
    }
}

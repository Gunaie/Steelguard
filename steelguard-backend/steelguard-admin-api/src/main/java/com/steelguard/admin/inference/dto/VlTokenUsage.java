package com.steelguard.admin.inference.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/**
 * Qwen-VL 大模型 token 用量(对应 Python VlDetectResponse.tokens)
 */
@Data
public class VlTokenUsage {

    @JsonProperty("prompt_tokens")
    private Integer promptTokens;

    @JsonProperty("completion_tokens")
    private Integer completionTokens;

    @JsonProperty("total_tokens")
    private Integer totalTokens;
}

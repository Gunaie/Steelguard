package com.steelguard.admin.inference.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * Qwen-VL 零样本检测响应(对应 Python /infer/detect-vl)
 * 与 YOLO DetectResponse 的区别: 无 device, 多 provider/tokens
 */
@Data
public class VlDetectResponse {

    private String model;

    /** 提供方: dashscope / ollama */
    private String provider;

    @JsonProperty("image_width")
    private Integer imageWidth;

    @JsonProperty("image_height")
    private Integer imageHeight;

    @JsonProperty("inference_ms")
    private Double inferenceMs;

    private Integer count;

    private List<Detection> detections;

    private VlTokenUsage tokens;
}

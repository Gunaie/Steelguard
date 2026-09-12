package com.steelguard.admin.inference.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * YOLO 检测响应(对应 Python /infer/detect)
 */
@Data
public class DetectResponse {

    private String model;

    /** 实际推理设备, 如 cuda:0 / cpu */
    private String device;

    @JsonProperty("image_width")
    private Integer imageWidth;

    @JsonProperty("image_height")
    private Integer imageHeight;

    @JsonProperty("inference_ms")
    private Double inferenceMs;

    private Integer count;

    private List<Detection> detections;
}

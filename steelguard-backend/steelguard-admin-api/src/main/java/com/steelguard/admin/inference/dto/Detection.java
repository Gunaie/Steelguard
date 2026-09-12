package com.steelguard.admin.inference.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/**
 * 单个缺陷检测结果(字段与 Python FastAPI 响应严格对齐)
 */
@Data
public class Detection {

    @JsonProperty("class_id")
    private Integer classId;

    @JsonProperty("class_name")
    private String className;

    @JsonProperty("class_name_cn")
    private String classNameCn;

    private Double confidence;

    private BBox bbox;
}

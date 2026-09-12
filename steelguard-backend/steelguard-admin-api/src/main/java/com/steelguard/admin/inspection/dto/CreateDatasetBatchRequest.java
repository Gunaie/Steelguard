package com.steelguard.admin.inspection.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

/**
 * 从数据集抽样创建质检批次(v1-raw 原图中随机抽 N 张)
 */
@Data
public class CreateDatasetBatchRequest {

    @NotBlank(message = "批次名称不能为空")
    @Size(max = 128)
    private String name;

    @Min(value = 1, message = "抽样数量至少 1")
    @Max(value = 1800, message = "单次最多 1800 张")
    private Integer sampleCount = 20;

    /** 限定抽样类别(6 类英文标识); 为空则全类别随机 */
    private List<String> classNames;

    /** 抽样随机种子(同种子可复现同一批图) */
    private Integer seed = 42;
}

package com.steelguard.admin.inspection.dto;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 批次列表行(不含明细)
 */
@Data
public class BatchVO {

    private Long id;
    private String batchNo;
    private String name;
    private String source;
    private String status;
    private String model;
    private Integer imageCount;
    private Integer processedCount;
    private Integer defectImageCount;
    private Integer defectCount;
    private Integer caseCount;
    private String severity;
    private Double totalInferenceMs;
    private String errorMsg;
    private Integer reported;
    private LocalDateTime createTime;
}

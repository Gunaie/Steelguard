package com.steelguard.admin.inspection.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 批次详情: 批次元信息 + 类别统计 + 检测明细(前 N 条) + 4.2 报告
 */
@Data
public class BatchDetailVO {

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
    private String reportJson;
    private String reportModel;
    private Integer llmTokens;
    private Integer reported;
    private LocalDateTime createTime;

    /** 批次内各类别案例数/平均置信度 */
    private List<Map<String, Object>> classStats;

    /** 明细(最多 limit 条, 1800 张历史批次不全量返回) */
    private List<RecordVO> records;

    private Long totalRecords;
}

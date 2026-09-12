package com.steelguard.admin.inspection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 质检批次表: 一次批量质检 = 一个批次
 * source: dataset=数据集抽样 / upload=现场上传 / history=历史基线库
 * status: pending -> detecting -> done / failed
 */
@Data
@TableName("inspect_batch")
public class InspectBatch {

    @TableId(type = IdType.AUTO)
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

    /** 程序规则定级 low/medium/high/critical(4.2 由 LLM 复核解读) */
    private String severity;

    private Double totalInferenceMs;

    private String errorMsg;

    /** 4.2 LLM 结构化报告 JSON 原文 */
    private String reportJson;

    private String reportModel;

    private Integer llmTokens;

    private Integer reported;

    private Long createdBy;

    @TableLogic
    private Integer deleted;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}

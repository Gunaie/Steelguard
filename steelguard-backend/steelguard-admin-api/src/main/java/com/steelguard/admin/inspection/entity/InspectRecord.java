package com.steelguard.admin.inspection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 单图检测记录表: 每张受检图一行, 检测框 JSON 原样留存
 */
@Data
@TableName("inspect_record")
public class InspectRecord {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long batchId;

    private String imageName;

    private Integer width;

    private Integer height;

    private String minioBucket;

    private String minioPath;

    private String model;

    private Double inferenceMs;

    private Integer detCount;

    /** Python 检测响应中的 detections 数组原文 */
    private String resultJson;

    /** dataset 来源时记录 dataset_image.id */
    private String sourceRef;

    private LocalDateTime createTime;
}

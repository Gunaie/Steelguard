package com.steelguard.admin.dataset.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 数据集版本表: 每次导入/增强产生一个版本(v1-raw / v1-aug5)
 */
@Data
@TableName("dataset_version")
public class DatasetVersion implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String version;

    private String datasetName;

    private String source;

    private Integer imageCount;

    private Integer annotationCount;

    private Integer augmentFactor;

    private Integer totalCount;

    /** draft / importing / ready / archived */
    private String status;

    private String remark;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}

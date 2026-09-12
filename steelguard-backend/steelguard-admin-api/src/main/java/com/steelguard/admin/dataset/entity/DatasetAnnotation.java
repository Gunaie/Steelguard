package com.steelguard.admin.dataset.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 数据集标注表: PascalVOC 绝对像素坐标, 每图可多框
 */
@Data
@TableName("dataset_annotation")
public class DatasetAnnotation implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long imageId;

    private String className;

    private Integer xmin;

    private Integer ymin;

    private Integer xmax;

    private Integer ymax;

    private LocalDateTime createTime;
}

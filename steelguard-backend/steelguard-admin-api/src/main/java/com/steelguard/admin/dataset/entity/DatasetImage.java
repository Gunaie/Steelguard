package com.steelguard.admin.dataset.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 数据集图片表: 1800 原始 + 7200 增强 = 9000 行
 */
@Data
@TableName("dataset_image")
public class DatasetImage implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long versionId;

    private String fileName;

    private String className;

    private Integer width;

    private Integer height;

    private Integer depth;

    private Long fileSize;

    private String minioPath;

    /** raw=原始, augmented=增强 */
    private String split;

    private Long sourceImageId;

    /** horizontal_flip / vertical_flip / rotate / brightness_contrast */
    private String augmentMethod;

    @TableLogic
    private Integer deleted;

    private LocalDateTime createTime;
}

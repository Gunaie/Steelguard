package com.steelguard.admin.inspection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 缺陷案例表: 每个检测框一行, Milvus 向量库的关系镜像
 * 相似度/向量在 Milvus, 业务元数据/裁剪图路径/统计在 MySQL
 */
@Data
@TableName("defect_case")
public class DefectCase {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long recordId;

    private Long batchId;

    private String className;

    private Double confidence;

    private Double x1;

    private Double y1;

    private Double x2;

    private Double y2;

    private String cropMinioPath;

    /** Milvus 主键: r{record_id}-{box_index} */
    private String milvusPk;

    private LocalDateTime createTime;
}

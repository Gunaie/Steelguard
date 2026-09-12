package com.steelguard.admin.dataset.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 数据集 EDA 统计结果
 */
@Data
public class DatasetEdaVO {

    private Long versionId;

    private String version;

    private String status;

    private Long totalImages;

    private Long totalAnnotations;

    private Double avgBboxesPerImage;

    /** 6 类分布 */
    private List<ClassCountItem> classDistribution;

    /** 每图框数分布 */
    private List<BboxCountItem> bboxPerImageDistribution;

    /** 增强方法分布(raw 版本只有一项 null) */
    private List<MethodCountItem> augmentMethodDistribution;

    /** 图像尺寸: {widthMin, widthMax, heightMin, heightMax, depths:[1]} */
    private Map<String, Object> imageSize;

    /** bbox 尺寸: {widthMin/Max/Avg, heightMin/Max/Avg, totalBboxes} */
    private Map<String, Object> bboxSize;
}

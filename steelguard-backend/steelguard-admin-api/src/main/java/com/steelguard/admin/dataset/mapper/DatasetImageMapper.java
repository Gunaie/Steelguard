package com.steelguard.admin.dataset.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.steelguard.admin.dataset.dto.BboxCountItem;
import com.steelguard.admin.dataset.dto.ClassCountItem;
import com.steelguard.admin.dataset.dto.MethodCountItem;
import com.steelguard.admin.dataset.entity.DatasetImage;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

@Mapper
public interface DatasetImageMapper extends BaseMapper<DatasetImage> {

    /** 类别分布: 每类图片数(按图片主类) + 该类图片上的标注框数 */
    @Select("""
            SELECT i.class_name AS className,
                   COUNT(DISTINCT i.id) AS imageCount,
                   COUNT(a.id) AS bboxCount
            FROM dataset_image i
            LEFT JOIN dataset_annotation a ON a.image_id = i.id
            WHERE i.version_id = #{versionId} AND i.deleted = 0
            GROUP BY i.class_name
            ORDER BY i.class_name
            """)
    List<ClassCountItem> selectClassDistribution(@Param("versionId") Long versionId);

    /** 每图框数分布 */
    @Select("""
            SELECT bboxCnt AS bboxCount, COUNT(*) AS imageCount
            FROM (
                SELECT i.id, COUNT(a.id) AS bboxCnt
                FROM dataset_image i
                LEFT JOIN dataset_annotation a ON a.image_id = i.id
                WHERE i.version_id = #{versionId} AND i.deleted = 0
                GROUP BY i.id
            ) t
            GROUP BY bboxCnt
            ORDER BY bboxCnt
            """)
    List<BboxCountItem> selectBboxPerImage(@Param("versionId") Long versionId);

    /** 增强方法分布 */
    @Select("""
            SELECT augment_method AS augmentMethod, COUNT(*) AS imageCount
            FROM dataset_image
            WHERE version_id = #{versionId} AND deleted = 0
            GROUP BY augment_method
            ORDER BY augmentMethod
            """)
    List<MethodCountItem> selectMethodDistribution(@Param("versionId") Long versionId);

    /** 图像尺寸极值与通道集合(GROUP_CONCAT 返回如 "1") */
    @Select("""
            SELECT MIN(width) AS widthMin, MAX(width) AS widthMax,
                   MIN(height) AS heightMin, MAX(height) AS heightMax,
                   GROUP_CONCAT(DISTINCT depth) AS depths
            FROM dataset_image
            WHERE version_id = #{versionId} AND deleted = 0
            """)
    Map<String, Object> selectImageSize(@Param("versionId") Long versionId);

    /** 标注框宽高统计 */
    @Select("""
            SELECT MIN(a.xmax - a.xmin) AS widthMin,
                   MAX(a.xmax - a.xmin) AS widthMax,
                   ROUND(AVG(a.xmax - a.xmin), 2) AS widthAvg,
                   MIN(a.ymax - a.ymin) AS heightMin,
                   MAX(a.ymax - a.ymin) AS heightMax,
                   ROUND(AVG(a.ymax - a.ymin), 2) AS heightAvg,
                   COUNT(*) AS totalBboxes
            FROM dataset_annotation a
            JOIN dataset_image i ON a.image_id = i.id
            WHERE i.version_id = #{versionId} AND i.deleted = 0
            """)
    Map<String, Object> selectBboxSize(@Param("versionId") Long versionId);
}

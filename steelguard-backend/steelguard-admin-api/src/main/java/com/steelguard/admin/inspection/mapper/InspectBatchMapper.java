package com.steelguard.admin.inspection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.steelguard.admin.inspection.entity.InspectBatch;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

@Mapper
public interface InspectBatchMapper extends BaseMapper<InspectBatch> {

    /** 已完成批次的图片/缺陷图/案例汇总(趋势看板 KPI); 自定义 SQL 需手动带逻辑删除条件 */
    @Select("""
            SELECT COALESCE(SUM(image_count), 0) AS totalImages,
                   COALESCE(SUM(defect_image_count), 0) AS totalDefectImages,
                   COALESCE(SUM(case_count), 0) AS totalCases
            FROM inspect_batch
            WHERE deleted = 0 AND status = 'done'
            """)
    Map<String, Object> selectDoneAggregate();

    /** 已完成批次按程序严重度定级分布(趋势看板) */
    @Select("""
            SELECT severity, COUNT(*) AS count
            FROM inspect_batch
            WHERE deleted = 0 AND status = 'done'
            GROUP BY severity
            """)
    List<Map<String, Object>> selectSeverityStats();
}

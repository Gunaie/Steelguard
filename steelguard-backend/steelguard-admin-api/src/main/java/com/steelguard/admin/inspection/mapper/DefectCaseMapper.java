package com.steelguard.admin.inspection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.steelguard.admin.inspection.entity.DefectCase;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

@Mapper
public interface DefectCaseMapper extends BaseMapper<DefectCase> {

    /** 批次内按类别统计案例数(报告事实 + 趋势看板) */
    @Select("""
            SELECT class_name AS className, COUNT(*) AS count,
                   ROUND(AVG(confidence), 4) AS avgConfidence
            FROM defect_case
            WHERE batch_id = #{batchId}
            GROUP BY class_name
            ORDER BY count DESC
            """)
    List<Map<String, Object>> selectClassStats(@Param("batchId") Long batchId);

    /** 全局每日新增缺陷案例数(趋势看板) */
    @Select("""
            SELECT DATE(create_time) AS date, COUNT(*) AS count
            FROM defect_case
            WHERE create_time >= #{fromDate}
            GROUP BY DATE(create_time)
            ORDER BY date
            """)
    List<Map<String, Object>> selectDailyCount(@Param("fromDate") String fromDate);

    /** 全局按类别统计案例数/平均置信度(趋势看板) */
    @Select("""
            SELECT class_name AS className, COUNT(*) AS count,
                   ROUND(AVG(confidence), 4) AS avgConfidence
            FROM defect_case
            GROUP BY class_name
            ORDER BY count DESC
            """)
    List<Map<String, Object>> selectGlobalClassStats();

    /**
     * 各缺陷类别中置信度最高的代表案例(给 Milvus 反查历史相似案例的锚点)。
     * 取本批次每个类别 confidence 最大的一行, 结果按该类案例数降序, 最多 3 类。
     * 返回字段: className, classCount, recordId, milvusPk, confidence。
     */
    @Select("""
            SELECT className, classCount, recordId, milvusPk, confidence FROM (
              SELECT class_name AS className,
                     COUNT(*) OVER (PARTITION BY class_name) AS classCount,
                     record_id AS recordId,
                     milvus_pk AS milvusPk,
                     confidence,
                     ROW_NUMBER() OVER (PARTITION BY class_name ORDER BY confidence DESC) AS rn
              FROM defect_case
              WHERE batch_id = #{batchId}
            ) t
            WHERE rn = 1
            ORDER BY classCount DESC
            LIMIT 3
            """)
    List<Map<String, Object>> selectRepresentatives(@Param("batchId") Long batchId);
}

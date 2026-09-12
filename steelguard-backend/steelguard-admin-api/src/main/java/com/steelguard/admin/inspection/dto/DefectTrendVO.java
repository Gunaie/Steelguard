package com.steelguard.admin.inspection.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 缺陷趋势看板数据(阶段 4.3):
 * KPI 汇总 + 类别分布 + 每日新增 + 批次严重度分布
 */
@Data
public class DefectTrendVO {

    /** 趋势窗口天数(7~365) */
    private long days;

    /** 窗口起始日期 yyyy-MM-dd */
    private String fromDate;

    // ---------- KPI(全部基于已完成 done 批次) ----------
    private long totalBatches;
    private long doneBatches;
    private long totalImages;
    private long totalDefectImages;
    /** 缺陷图占比 = 缺陷图数 / 已检图片总数 */
    private double defectImageRate;
    /** 入向量库缺陷案例总数 */
    private long totalCases;
    /** 全部案例平均检测置信度 */
    private double avgConfidence;

    /** 六类缺陷案例分布: className/count/avgConfidence */
    private List<Map<String, Object>> classDistribution;

    /** 已完成批次严重度分布: severity/count */
    private List<Map<String, Object>> severityDistribution;

    /** 窗口内每日新增缺陷案例(无数据日期补 0): date/count */
    private List<DailyCount> daily;

    @Data
    public static class DailyCount {
        private String date;
        private long count;

        public DailyCount(String date, long count) {
            this.date = date;
            this.count = count;
        }
    }
}

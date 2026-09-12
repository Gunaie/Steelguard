package com.steelguard.admin.inspection.service;

/**
 * 批次严重度程序定级规则(4.1 版本)
 *
 * 4.2 起 LLM 只在此客观结论上做解读与处置建议, 数字本身永远由程序计算, 杜绝幻觉。
 * 依据:
 * - 缺陷率 rate   = 有缺陷图数 / 总图数
 * - 框密度 density = 缺陷框总数 / 总图数(本数据集平均约 2.33)
 * - 高危占比 highRatio = (裂纹 crazing + 划痕 scratches) / 缺陷框总数
 *   （裂纹/划痕直接影响板材疲劳寿命与后续涂镀, 工业实践中风险权重高）
 */
public final class SeverityRules {

    public static final String LOW = "low";
    public static final String MEDIUM = "medium";
    public static final String HIGH = "high";
    public static final String CRITICAL = "critical";

    private SeverityRules() {
    }

    public static String judge(int imageCount, int defectImageCount,
                               int defectCount, int highRiskCount) {
        if (imageCount <= 0 || defectCount == 0) {
            return LOW;
        }
        double rate = (double) defectImageCount / imageCount;
        double density = (double) defectCount / imageCount;
        double highRatio = (double) highRiskCount / defectCount;

        if (density >= 3.0 || (rate >= 0.8 && highRatio >= 0.4)) {
            return CRITICAL;
        }
        if (density >= 1.5 || rate >= 0.5) {
            return HIGH;
        }
        if (density >= 0.5 || rate >= 0.2) {
            return MEDIUM;
        }
        return LOW;
    }
}

package com.steelguard.admin.inspection.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 批次严重度规则定级测试(纯函数, 覆盖各档边界)
 */
class SeverityRulesTest {

    @Test
    @DisplayName("无图片或无缺陷 -> low")
    void noDefectLow() {
        assertEquals(SeverityRules.LOW, SeverityRules.judge(0, 0, 0, 0));
        assertEquals(SeverityRules.LOW, SeverityRules.judge(10, 0, 0, 0));
    }

    @Test
    @DisplayName("框密度 >=3 -> critical, 与高危占比无关")
    void densityCritical() {
        // 10 图 30 框, density=3.0, 即使无高危类也是 critical
        assertEquals(SeverityRules.CRITICAL, SeverityRules.judge(10, 10, 30, 0));
    }

    @Test
    @DisplayName("缺陷率 >=0.8 且高危占比 >=0.4 -> critical")
    void rateAndHighRiskCritical() {
        // 8/10 图有缺陷(rate=0.8), 10 个框中 4 个高危(highRatio=0.4), density=1.0
        assertEquals(SeverityRules.CRITICAL, SeverityRules.judge(10, 8, 10, 4));
    }

    @Test
    @DisplayName("高缺陷率但高危占比不足 -> 退档 high 而非 critical")
    void highRateWithoutEnoughHighRisk() {
        // rate=0.8, highRatio=0.3, density=1.0 -> 不满足 critical, rate>=0.5 -> high
        assertEquals(SeverityRules.HIGH, SeverityRules.judge(10, 8, 10, 3));
    }

    @Test
    @DisplayName("框密度 >=1.5 -> high")
    void densityHigh() {
        // density=1.5, rate=0.3
        assertEquals(SeverityRules.HIGH, SeverityRules.judge(10, 3, 15, 0));
    }

    @Test
    @DisplayName("缺陷率 >=0.5 -> high")
    void rateHigh() {
        // rate=0.5, density=0.5(单看密度只够 medium), 规则取高档
        assertEquals(SeverityRules.HIGH, SeverityRules.judge(10, 5, 5, 0));
    }

    @Test
    @DisplayName("中等档边界: rate=0.2 或 density=0.5 -> medium")
    void mediumBoundaries() {
        assertEquals(SeverityRules.MEDIUM, SeverityRules.judge(10, 2, 2, 0));
        assertEquals(SeverityRules.MEDIUM, SeverityRules.judge(10, 1, 5, 0));
    }

    @Test
    @DisplayName("低缺陷率低密度 -> low")
    void low() {
        assertEquals(SeverityRules.LOW, SeverityRules.judge(10, 1, 1, 0));
    }
}

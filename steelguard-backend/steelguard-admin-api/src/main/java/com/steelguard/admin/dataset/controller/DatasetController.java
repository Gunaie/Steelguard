package com.steelguard.admin.dataset.controller;

import com.steelguard.admin.dataset.dto.DatasetEdaVO;
import com.steelguard.admin.dataset.dto.DatasetImageVO;
import com.steelguard.admin.dataset.dto.PageResult;
import com.steelguard.admin.dataset.entity.DatasetVersion;
import com.steelguard.admin.dataset.service.DatasetService;
import com.steelguard.common.result.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 数据集查询: 版本 / EDA 统计 / 图片分页(预签名缩略图)
 */
@Tag(name = "数据集工程")
@RestController
@RequestMapping("/dataset")
@RequiredArgsConstructor
public class DatasetController {

    private final DatasetService datasetService;

    @Operation(summary = "数据集版本列表")
    @GetMapping("/versions")
    public Result<List<DatasetVersion>> versions() {
        return Result.ok(datasetService.listVersions());
    }

    @Operation(summary = "EDA 统计(类别/框数/尺寸/增强方法分布)")
    @GetMapping("/eda")
    public Result<DatasetEdaVO> eda(
            @Parameter(description = "版本ID, 不传取最新版本")
            @RequestParam(required = false) Long versionId) {
        return Result.ok(datasetService.getEda(versionId));
    }

    @Operation(summary = "图片分页查询(返回 MinIO 预签名 URL)")
    @GetMapping("/images")
    public Result<PageResult<DatasetImageVO>> images(
            @RequestParam(required = false) Long versionId,
            @Parameter(description = "缺陷类别(6 类之一)")
            @RequestParam(required = false) String className,
            @Parameter(description = "raw / augmented")
            @RequestParam(required = false) String split,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "12") long size) {
        return Result.ok(datasetService.pageImages(versionId, className, split, page, size));
    }
}

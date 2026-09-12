package com.steelguard.admin.inspection.controller;

import com.steelguard.admin.dataset.dto.PageResult;
import com.steelguard.admin.inspection.dto.BatchDetailVO;
import com.steelguard.admin.inspection.dto.BatchVO;
import com.steelguard.admin.inspection.dto.CreateDatasetBatchRequest;
import com.steelguard.admin.inspection.dto.DefectTrendVO;
import com.steelguard.admin.inspection.entity.InspectBatch;
import com.steelguard.admin.inspection.service.InspectionService;
import com.steelguard.admin.security.LoginUser;
import com.steelguard.common.result.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 质检批次: 创建(数据集抽样/现场上传) / 异步跑批 / 列表与详情
 */
@Tag(name = "质检批次")
@RestController
@RequestMapping("/inspection")
@RequiredArgsConstructor
public class InspectionController {

    private final InspectionService inspectionService;

    @Operation(summary = "从 NEU-DET 数据集随机抽样创建批次(不立即开跑)")
    @PostMapping("/batches/dataset")
    public Result<BatchVO> createFromDataset(@Valid @RequestBody CreateDatasetBatchRequest req) {
        InspectBatch batch = inspectionService.createFromDataset(req, currentUserId());
        return Result.ok(inspectionService.toBatchVO(batch));
    }

    @Operation(summary = "上传现场图片创建批次(最多 50 张)")
    @PostMapping(value = "/batches/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<BatchVO> createFromUpload(@RequestParam("name") String name,
                                            @RequestParam("files") List<MultipartFile> files) {
        InspectBatch batch = inspectionService.createFromUpload(name, files, currentUserId());
        return Result.ok(inspectionService.toBatchVO(batch));
    }

    @Operation(summary = "启动批次异步跑批(YOLO 检测 + 缺陷入向量库)")
    @PostMapping("/batches/{id}/run")
    public Result<String> run(@PathVariable Long id) {
        inspectionService.runBatch(id);
        return Result.ok("批次已开始处理");
    }

    @Operation(summary = "批次分页列表")
    @GetMapping("/batches")
    public Result<PageResult<BatchVO>> page(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String status) {
        return Result.ok(inspectionService.pageBatches(page, size, status));
    }

    @Operation(summary = "批次详情(统计 + 前 N 条检测明细)")
    @GetMapping("/batches/{id}")
    public Result<BatchDetailVO> detail(
            @PathVariable Long id,
            @RequestParam(defaultValue = "100") long limit) {
        return Result.ok(inspectionService.getDetail(id, limit));
    }

    @Operation(summary = "生成批次结构化质检报告(qwen-plus, 事实注入+JSON Schema 校验)")
    @PostMapping("/batches/{id}/report")
    public Result<String> generateReport(@PathVariable Long id) {
        String model = inspectionService.generateReport(id);
        return Result.ok("报告已生成, 模型: " + model);
    }

    @Operation(summary = "缺陷趋势看板(KPI/六类分布/每日新增/严重度分布)")
    @GetMapping("/stats/trend")
    public Result<DefectTrendVO> trend(@RequestParam(defaultValue = "30") Long days) {
        return Result.ok(inspectionService.getDefectTrend(days));
    }

    private Long currentUserId() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof LoginUser loginUser) {
            return loginUser.getUserId();
        }
        return null;
    }
}

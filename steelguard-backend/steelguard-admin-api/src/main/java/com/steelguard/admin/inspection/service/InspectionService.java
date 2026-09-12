package com.steelguard.admin.inspection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.steelguard.admin.dataset.dto.PageResult;
import com.steelguard.admin.dataset.entity.DatasetImage;
import com.steelguard.admin.dataset.entity.DatasetVersion;
import com.steelguard.admin.dataset.mapper.DatasetImageMapper;
import com.steelguard.admin.dataset.mapper.DatasetVersionMapper;
import com.steelguard.admin.inference.dto.DetectResponse;
import com.steelguard.admin.inspection.dto.AiDetectUrlRequest;
import com.steelguard.admin.inspection.dto.AiReportRequest;
import com.steelguard.admin.inspection.dto.AiReportResponse;
import com.steelguard.admin.inspection.dto.AiTraceIndexRequest;
import com.steelguard.admin.inspection.dto.AiTraceIndexResponse;
import com.steelguard.admin.inspection.dto.BatchDetailVO;
import com.steelguard.admin.inspection.dto.BatchVO;
import com.steelguard.admin.inspection.dto.CreateDatasetBatchRequest;
import com.steelguard.admin.inspection.dto.DefectTrendVO;
import com.steelguard.admin.inspection.dto.RecordVO;
import com.steelguard.admin.inspection.entity.DefectCase;
import com.steelguard.admin.inspection.entity.InspectBatch;
import com.steelguard.admin.inspection.entity.InspectRecord;
import com.steelguard.admin.inspection.mapper.DefectCaseMapper;
import com.steelguard.admin.inspection.mapper.InspectBatchMapper;
import com.steelguard.admin.inspection.mapper.InspectRecordMapper;
import com.steelguard.common.exception.BusinessException;
import io.minio.GetPresignedObjectUrlArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.http.Method;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 质检批次服务: 创建批次(数据集抽样/现场上传) + 异步跑批编排
 *
 * 跑批链路(每张图):
 * MinIO 预签名 URL -> Python /infer/detect-url(YOLO) -> inspect_record 落库
 *                 -> Python /trace/index(裁剪->ResNet50->Milvus+defect_case)
 * 单张失败不中断整批, 错误汇总进 error_msg。
 */
@Slf4j
@Service
public class InspectionService {

    /** NEU-DET 六类英文标识白名单 */
    private static final Set<String> ALLOWED_CLASSES =
            Set.of("crazing", "inclusion", "patches", "pitted_surface", "rolled-in_scale", "scratches");

    /** 六类中文别名(报告 class_stats.class_name_cn 用) */
    private static final Map<String, String> CLASS_NAME_CN = Map.of(
            "crazing", "裂纹",
            "inclusion", "夹杂",
            "patches", "斑块",
            "pitted_surface", "麻点",
            "rolled-in_scale", "氧化皮",
            "scratches", "划痕");

    /** 严重度高风险类: 裂纹/划痕(影响板材疲劳寿命与后续涂镀) */
    private static final Set<String> HIGH_RISK_CLASSES = Set.of("crazing", "scratches");

    private static final String RAW_VERSION = "v1-raw";
    private static final DateTimeFormatter BATCH_NO_FMT = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    private final InspectBatchMapper batchMapper;
    private final InspectRecordMapper recordMapper;
    private final DefectCaseMapper caseMapper;
    private final DatasetVersionMapper versionMapper;
    private final DatasetImageMapper datasetImageMapper;
    private final MinioClient minioClient;
    private final MinioClient presignMinioClient;
    private final RestClient aiServiceClient;
    private final RestClient aiServiceTraceClient;
    private final RestClient aiServiceReportClient;
    private final ObjectMapper objectMapper;

    @Value("${minio.bucket:defect-images}")
    private String defectBucket;

    @Value("${minio.datasets-bucket:datasets}")
    private String datasetsBucket;

    public InspectionService(InspectBatchMapper batchMapper,
                             InspectRecordMapper recordMapper,
                             DefectCaseMapper caseMapper,
                             DatasetVersionMapper versionMapper,
                             DatasetImageMapper datasetImageMapper,
                             MinioClient minioClient,
                             @Qualifier("presignMinioClient") MinioClient presignMinioClient,
                             @Qualifier("aiServiceClient") RestClient aiServiceClient,
                             @Qualifier("aiServiceTraceClient") RestClient aiServiceTraceClient,
                             @Qualifier("aiServiceReportClient") RestClient aiServiceReportClient,
                             ObjectMapper objectMapper) {
        this.batchMapper = batchMapper;
        this.recordMapper = recordMapper;
        this.caseMapper = caseMapper;
        this.versionMapper = versionMapper;
        this.datasetImageMapper = datasetImageMapper;
        this.minioClient = minioClient;
        this.presignMinioClient = presignMinioClient;
        this.aiServiceClient = aiServiceClient;
        this.aiServiceTraceClient = aiServiceTraceClient;
        this.aiServiceReportClient = aiServiceReportClient;
        this.objectMapper = objectMapper;
    }

    // ==================== 创建批次 ====================

    /** 从 v1-raw 原图随机抽样建批 */
    public InspectBatch createFromDataset(CreateDatasetBatchRequest req, Long userId) {
        if (!CollectionUtils.isEmpty(req.getClassNames())) {
            for (String cn : req.getClassNames()) {
                if (!ALLOWED_CLASSES.contains(cn)) {
                    throw new BusinessException(400, "非法缺陷类别: " + cn);
                }
            }
        }
        DatasetVersion version = versionMapper.selectOne(
                new LambdaQueryWrapper<DatasetVersion>()
                        .eq(DatasetVersion::getVersion, RAW_VERSION)
                        .last("LIMIT 1"));
        if (version == null) {
            throw new BusinessException(500, "数据集版本 v1-raw 不存在, 无法抽样");
        }

        int seed = req.getSeed() == null ? 42 : req.getSeed();
        // RAND(seed) 同种子可复现; seed 为 int, 无注入风险
        LambdaQueryWrapper<DatasetImage> qw = new LambdaQueryWrapper<DatasetImage>()
                .eq(DatasetImage::getVersionId, version.getId())
                .eq(DatasetImage::getSplit, "raw")
                .in(!CollectionUtils.isEmpty(req.getClassNames()),
                        DatasetImage::getClassName, req.getClassNames())
                .last("ORDER BY RAND(" + seed + ") LIMIT " + req.getSampleCount());
        List<DatasetImage> samples = datasetImageMapper.selectList(qw);
        if (samples.isEmpty()) {
            throw new BusinessException(400, "抽样结果为空, 请调整类别或数量");
        }

        InspectBatch batch = newBatch(req.getName(), "dataset", samples.size(), userId);
        batchMapper.insert(batch);

        List<InspectRecord> records = new ArrayList<>(samples.size());
        for (DatasetImage img : samples) {
            InspectRecord r = new InspectRecord();
            r.setBatchId(batch.getId());
            r.setImageName(img.getFileName());
            r.setWidth(img.getWidth());
            r.setHeight(img.getHeight());
            r.setMinioBucket(datasetsBucket);
            r.setMinioPath(img.getMinioPath());
            r.setDetCount(0);
            r.setSourceRef(String.valueOf(img.getId()));
            records.add(r);
        }
        saveRecords(records);
        log.info("创建数据集抽样批次 id={} no={} 抽 {} 张", batch.getId(), batch.getBatchNo(), records.size());
        return batch;
    }

    /** 现场多图上传建批(图片先传 MinIO inspect/{batchNo}/) */
    public InspectBatch createFromUpload(String name, List<MultipartFile> files, Long userId) {
        if (CollectionUtils.isEmpty(files)) {
            throw new BusinessException(400, "上传文件为空");
        }
        if (files.size() > 50) {
            throw new BusinessException(400, "单批次最多上传 50 张");
        }
        InspectBatch batch = newBatch(name, "upload", files.size(), userId);
        batchMapper.insert(batch);

        List<InspectRecord> records = new ArrayList<>(files.size());
        for (MultipartFile file : files) {
            if (file.isEmpty()) {
                continue;
            }
            String safeName = sanitizeFileName(file.getOriginalFilename());
            String objectPath = "inspect/" + batch.getBatchNo() + "/"
                    + System.currentTimeMillis() + "-" + safeName;
            try {
                minioClient.putObject(PutObjectArgs.builder()
                        .bucket(defectBucket)
                        .object(objectPath)
                        .stream(file.getInputStream(), file.getSize(), 10 * 1024 * 1024L)
                        .contentType(StringUtils.hasText(file.getContentType())
                                ? file.getContentType() : "image/jpeg")
                        .build());
            } catch (Exception e) {
                throw new BusinessException(500, "图片上传 MinIO 失败: " + safeName + " " + e.getMessage());
            }
            InspectRecord r = new InspectRecord();
            r.setBatchId(batch.getId());
            r.setImageName(safeName);
            r.setMinioBucket(defectBucket);
            r.setMinioPath(objectPath);
            r.setDetCount(0);
            records.add(r);
        }
        if (records.isEmpty()) {
            throw new BusinessException(400, "上传文件全部为空");
        }
        batch.setImageCount(records.size());
        batchMapper.updateById(batch);
        saveRecords(records);
        log.info("创建上传批次 id={} no={} {} 张", batch.getId(), batch.getBatchNo(), records.size());
        return batch;
    }

    // ==================== 异步跑批 ====================

    /**
     * 异步跑批; 仅 pending/failed 状态可启动。
     * 注意 @Async 必须由其他 Bean 调用才生效(不要在本类内部自调用)。
     */
    @Async("batchExecutor")
    public void runBatch(Long batchId) {
        InspectBatch batch = batchMapper.selectById(batchId);
        if (batch == null) {
            log.warn("跑批目标批次不存在: {}", batchId);
            return;
        }
        if (!Set.of("pending", "failed").contains(batch.getStatus())) {
            log.info("批次 {} 状态为 {}, 跳过跑批", batchId, batch.getStatus());
            return;
        }
        batch.setStatus("detecting");
        batch.setErrorMsg(null);
        batchMapper.updateById(batch);

        List<InspectRecord> records = recordMapper.selectList(
                new LambdaQueryWrapper<InspectRecord>()
                        .eq(InspectRecord::getBatchId, batchId)
                        .orderByAsc(InspectRecord::getId));

        int processed = 0;
        int failed = 0;
        List<String> errors = new ArrayList<>();
        for (InspectRecord r : records) {
            try {
                processOneRecord(batch, r);
            } catch (Exception e) {
                failed++;
                String msg = r.getImageName() + ": " + truncate(e.getMessage(), 120);
                errors.add(msg);
                log.warn("批次 {} 图片 {} 处理失败: {}", batchId, r.getImageName(), e.toString());
            }
            processed++;
            // 每张完成即更新进度(批次上限 50 张, 写压力可忽略, 前端轮询可见实时进度)
            batch.setProcessedCount(processed);
            batchMapper.updateById(batch);
        }

        finalizeBatch(batch, records.size(), failed, errors);
    }

    /** 单图: YOLO 检测 -> record 落库 -> 入向量库 */
    private void processOneRecord(InspectBatch batch, InspectRecord r) {
        String url = presignedUrl(r.getMinioBucket(), r.getMinioPath(), 2);
        DetectResponse resp;
        try {
            resp = aiServiceClient.post()
                    .uri("/infer/detect-url")
                    .body(new AiDetectUrlRequest(url, 0.25, 0.7))
                    .retrieve()
                    .body(DetectResponse.class);
        } catch (HttpStatusCodeException e) {
            throw new BusinessException(e.getStatusCode().value(),
                    "AI 服务: " + extractDetail(e.getResponseBodyAsString()));
        }
        if (resp == null) {
            throw new BusinessException(502, "AI 服务返回空响应");
        }

        r.setWidth(resp.getImageWidth());
        r.setHeight(resp.getImageHeight());
        r.setModel(resp.getModel());
        r.setInferenceMs(resp.getInferenceMs());
        r.setDetCount(resp.getCount() == null ? 0 : resp.getCount());
        try {
            r.setResultJson(objectMapper.writeValueAsString(resp.getDetections()));
        } catch (Exception e) {
            throw new BusinessException(500, "检测结果序列化失败: " + e.getMessage());
        }
        recordMapper.updateById(r);

        if (r.getDetCount() > 0) {
            AiTraceIndexRequest idxReq = new AiTraceIndexRequest();
            idxReq.setRecordId(r.getId());
            idxReq.setBatchId(batch.getId());
            idxReq.setImageBucket(r.getMinioBucket());
            idxReq.setImageObject(r.getMinioPath());
            idxReq.setDetections(resp.getDetections());
            try {
                AiTraceIndexResponse idxResp = aiServiceTraceClient.post()
                        .uri("/trace/index")
                        .body(idxReq)
                        .retrieve()
                        .body(AiTraceIndexResponse.class);
                int indexed = idxResp == null || idxResp.getIndexed() == null ? 0 : idxResp.getIndexed();
                if (indexed == 0) {
                    log.warn("记录 {} 有 {} 个检测框但向量入库 0 条", r.getId(), r.getDetCount());
                }
            } catch (HttpStatusCodeException e) {
                // 向量入库失败不判定整图失败(检测结果已成功), 仅打警告
                log.warn("记录 {} 向量入库失败 HTTP{}: {}",
                        r.getId(), e.getStatusCode().value(),
                        extractDetail(e.getResponseBodyAsString()));
            }
        }
    }

    /** 收尾: 汇总统计 + 规则定级 + 状态流转 */
    private void finalizeBatch(InspectBatch batch, int total, int failed, List<String> errors) {
        Long batchId = batch.getId();
        Long defectImages = recordMapper.selectCount(
                new LambdaQueryWrapper<InspectRecord>()
                        .eq(InspectRecord::getBatchId, batchId)
                        .gt(InspectRecord::getDetCount, 0));
        Long caseCount = caseMapper.selectCount(
                new LambdaQueryWrapper<DefectCase>()
                        .eq(DefectCase::getBatchId, batchId));
        Long highRisk = caseMapper.selectCount(
                new LambdaQueryWrapper<DefectCase>()
                        .eq(DefectCase::getBatchId, batchId)
                        .in(DefectCase::getClassName, HIGH_RISK_CLASSES));

        // 推理总耗时与模型取记录聚合
        List<InspectRecord> done = recordMapper.selectList(
                new LambdaQueryWrapper<InspectRecord>().eq(InspectRecord::getBatchId, batchId));
        double inferTotal = done.stream()
                .filter(r -> r.getInferenceMs() != null)
                .mapToDouble(InspectRecord::getInferenceMs).sum();
        String model = done.stream().map(InspectRecord::getModel)
                .filter(StringUtils::hasText).findFirst().orElse(null);
        int defectCount = done.stream().mapToInt(r -> r.getDetCount() == null ? 0 : r.getDetCount()).sum();

        batch.setProcessedCount(total);
        batch.setDefectImageCount(defectImages.intValue());
        batch.setDefectCount(defectCount);
        batch.setCaseCount(caseCount.intValue());
        batch.setTotalInferenceMs(Math.round(inferTotal * 100.0) / 100.0);
        batch.setModel(model);
        batch.setSeverity(SeverityRules.judge(total, defectImages.intValue(),
                defectCount, highRisk.intValue()));
        // 全部失败才 failed; 部分失败仍 done, 错误写入 errorMsg
        batch.setStatus(failed == total && total > 0 ? "failed" : "done");
        if (!errors.isEmpty()) {
            String summary = failed + " 张失败: " + String.join("; ", errors);
            batch.setErrorMsg(truncate(summary, 480));
        } else {
            batch.setErrorMsg(null);
        }
        batchMapper.updateById(batch);
        log.info("批次 {} 完成 status={} images={} defects={} cases={} severity={}",
                batchId, batch.getStatus(), total, defectCount, caseCount, batch.getSeverity());
    }

    // ==================== 查询 ====================

    public PageResult<BatchVO> pageBatches(long page, long size, String status) {
        if (page < 1) {
            page = 1;
        }
        if (size < 1 || size > 100) {
            size = 10;
        }
        Page<InspectBatch> pg = batchMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<InspectBatch>()
                        .eq(StringUtils.hasText(status), InspectBatch::getStatus, status)
                        .orderByDesc(InspectBatch::getId));
        List<BatchVO> list = pg.getRecords().stream().map(this::toBatchVO).toList();
        return new PageResult<>(pg.getTotal(), page, size, list);
    }

    public BatchDetailVO getDetail(Long id, long recordLimit) {
        InspectBatch batch = batchMapper.selectById(id);
        if (batch == null) {
            throw new BusinessException(40404, "批次不存在: " + id);
        }
        if (recordLimit <= 0 || recordLimit > 200) {
            recordLimit = 100;
        }
        long totalRecords = recordMapper.selectCount(
                new LambdaQueryWrapper<InspectRecord>().eq(InspectRecord::getBatchId, id));
        List<InspectRecord> records = recordMapper.selectList(
                new LambdaQueryWrapper<InspectRecord>()
                        .eq(InspectRecord::getBatchId, id)
                        .orderByDesc(InspectRecord::getDetCount)
                        .last("LIMIT " + recordLimit));

        BatchDetailVO vo = new BatchDetailVO();
        copyBatchFields(batch, vo);
        // 报告内相似案例预签名 URL 仅 1h 有效, 读取详情时按 milvus_pk 重新签名
        vo.setReportJson(refreshReportUrls(vo.getReportJson()));
        vo.setTotalRecords(totalRecords);
        vo.setClassStats(caseMapper.selectClassStats(id));
        List<RecordVO> rvos = new ArrayList<>(records.size());
        for (InspectRecord r : records) {
            RecordVO rv = new RecordVO();
            rv.setId(r.getId());
            rv.setImageName(r.getImageName());
            rv.setWidth(r.getWidth());
            rv.setHeight(r.getHeight());
            rv.setModel(r.getModel());
            rv.setInferenceMs(r.getInferenceMs());
            rv.setDetCount(r.getDetCount());
            rv.setResultJson(r.getResultJson());
            rv.setUrl(presignedUrl(r.getMinioBucket(), r.getMinioPath(), 1));
            rvos.add(rv);
        }
        vo.setRecords(rvos);
        return vo;
    }

    // ==================== 4.3 趋势看板 ====================

    /**
     * 缺陷趋势看板聚合: KPI + 六类分布 + 每日新增 + 严重度分布。
     * KPI 仅统计 done 批次(检测完成的有效数据); 每日新增取 defect_case 全量。
     */
    public DefectTrendVO getDefectTrend(Long days) {
        long d = days == null ? 30 : days;
        if (d < 7) {
            d = 7;
        }
        if (d > 365) {
            d = 365;
        }
        LocalDate from = LocalDate.now().minusDays(d - 1);

        DefectTrendVO vo = new DefectTrendVO();
        vo.setDays(d);
        vo.setFromDate(from.toString());

        vo.setTotalBatches(batchMapper.selectCount(null));
        vo.setDoneBatches(batchMapper.selectCount(
                new LambdaQueryWrapper<InspectBatch>().eq(InspectBatch::getStatus, "done")));

        Map<String, Object> agg = batchMapper.selectDoneAggregate();
        long totalImages = toLong(agg == null ? null : agg.get("totalImages"));
        long totalDefectImages = toLong(agg == null ? null : agg.get("totalDefectImages"));
        vo.setTotalImages(totalImages);
        vo.setTotalDefectImages(totalDefectImages);
        vo.setDefectImageRate(totalImages > 0
                ? Math.round((double) totalDefectImages / totalImages * 10000.0) / 10000.0
                : 0.0);
        vo.setTotalCases(toLong(agg == null ? null : agg.get("totalCases")));

        List<Map<String, Object>> classDist = caseMapper.selectGlobalClassStats();
        vo.setClassDistribution(classDist);
        // 全局平均置信度: 以各类案例数为权重的加权平均
        double weighted = 0;
        long sum = 0;
        for (Map<String, Object> m : classDist) {
            long cnt = toLong(m.get("count"));
            weighted += cnt * toDouble(m.get("avgConfidence"));
            sum += cnt;
        }
        vo.setAvgConfidence(sum > 0 ? Math.round(weighted / sum * 10000.0) / 10000.0 : 0.0);

        vo.setSeverityDistribution(batchMapper.selectSeverityStats());

        // SQL 只返回有数据的日期, 前端折线需要连续时间轴 -> 服务端补齐 0
        List<Map<String, Object>> rows = caseMapper.selectDailyCount(from.toString());
        Map<String, Long> byDate = new LinkedHashMap<>();
        for (Map<String, Object> m : rows) {
            Object date = m.get("date");
            if (date != null) {
                byDate.put(date.toString(), toLong(m.get("count")));
            }
        }
        List<DefectTrendVO.DailyCount> daily = new ArrayList<>((int) d);
        for (long i = 0; i < d; i++) {
            String day = from.plusDays(i).toString();
            daily.add(new DefectTrendVO.DailyCount(day, byDate.getOrDefault(day, 0L)));
        }
        vo.setDaily(daily);
        return vo;
    }

    /**
     * 报告相似案例预签名 URL 刷新(报告生成时签名有效期 1 小时):
     * 按 similar_cases[].milvus_pk 回查 defect_case / inspect_record 重新签名,
     * 仅作用于接口返回值, 不回写数据库(库里存的报告原文保持不变)。
     */
    private String refreshReportUrls(String reportJson) {
        if (!StringUtils.hasText(reportJson)) {
            return reportJson;
        }
        try {
            JsonNode root = objectMapper.readTree(reportJson);
            JsonNode similar = root.get("similar_cases");
            if (similar == null || !similar.isArray() || similar.isEmpty()) {
                return reportJson;
            }
            List<String> pks = new ArrayList<>();
            for (JsonNode c : similar) {
                JsonNode pk = c.get("milvus_pk");
                if (pk != null && StringUtils.hasText(pk.asText())) {
                    pks.add(pk.asText());
                }
            }
            if (pks.isEmpty()) {
                return reportJson;
            }
            Map<String, DefectCase> caseByPk = caseMapper.selectList(
                            new LambdaQueryWrapper<DefectCase>().in(DefectCase::getMilvusPk, pks))
                    .stream().collect(Collectors.toMap(
                            DefectCase::getMilvusPk, c -> c, (a, b) -> a));
            List<Long> recordIds = caseByPk.values().stream()
                    .map(DefectCase::getRecordId).distinct().toList();
            Map<Long, InspectRecord> recordById = recordIds.isEmpty()
                    ? Map.of()
                    : recordMapper.selectList(new LambdaQueryWrapper<InspectRecord>()
                                    .in(InspectRecord::getId, recordIds)).stream()
                            .collect(Collectors.toMap(InspectRecord::getId, r -> r, (a, b) -> a));

            for (JsonNode c : similar) {
                JsonNode pkNode = c.get("milvus_pk");
                if (pkNode == null || !c.isObject()) {
                    continue;
                }
                DefectCase dc = caseByPk.get(pkNode.asText());
                if (dc == null) {
                    continue;
                }
                ObjectNode on = (ObjectNode) c;
                if (StringUtils.hasText(dc.getCropMinioPath())) {
                    on.put("crop_url", presignedUrl(defectBucket, dc.getCropMinioPath(), 1));
                }
                InspectRecord rec = recordById.get(dc.getRecordId());
                if (rec != null && StringUtils.hasText(rec.getMinioPath())) {
                    String bucket = StringUtils.hasText(rec.getMinioBucket())
                            ? rec.getMinioBucket() : defectBucket;
                    on.put("source_image_url", presignedUrl(bucket, rec.getMinioPath(), 1));
                }
            }
            return objectMapper.writeValueAsString(root);
        } catch (Exception e) {
            log.warn("刷新报告相似案例 URL 失败, 返回报告原文: {}", e.getMessage());
            return reportJson;
        }
    }

    // ==================== 4.2 LLM 结构化报告 ====================

    /**
     * 生成批次结构化质检报告(qwen-plus)。
     *
     * 防幻觉边界: 所有数字(缺陷数/占比/严重度/耗时)由本方法从 MySQL 聚合后注入,
     * LLM 只产出文字结论; 最终报告在 Python 侧经 JSON Schema 强校验+修复重试,
     * 不合格绝不落库。
     *
     * @return 报告生成模型名(供前端展示)
     */
    public String generateReport(Long batchId) {
        InspectBatch batch = batchMapper.selectById(batchId);
        if (batch == null) {
            throw new BusinessException(40404, "批次不存在: " + batchId);
        }
        if (!Set.of("done", "failed").contains(batch.getStatus())) {
            throw new BusinessException(400, "批次尚未完成检测, 无法生成报告(status="
                    + batch.getStatus() + ")");
        }

        // 1. 程序事实聚合
        int imageCount = nz(batch.getImageCount());
        int defectImageCount = nz(batch.getDefectImageCount());
        int defectCount = nz(batch.getDefectCount());
        int caseCount = nz(batch.getCaseCount());
        double defectRate = imageCount > 0 ? (double) defectImageCount / imageCount : 0.0;
        double boxDensity = imageCount > 0 ? (double) defectCount / imageCount : 0.0;
        double avgInferenceMs = batch.getTotalInferenceMs() != null && imageCount > 0
                ? batch.getTotalInferenceMs() / imageCount : 0.0;

        Long highRisk = caseMapper.selectCount(
                new LambdaQueryWrapper<DefectCase>()
                        .eq(DefectCase::getBatchId, batchId)
                        .in(DefectCase::getClassName, HIGH_RISK_CLASSES));

        AiReportRequest.BatchFacts facts = new AiReportRequest.BatchFacts();
        facts.setBatchId(batch.getId());
        facts.setBatchNo(batch.getBatchNo());
        facts.setName(batch.getName());
        facts.setSource(batch.getSource());
        facts.setDetectModel(batch.getModel());
        facts.setImageCount(imageCount);
        facts.setDefectImageCount(defectImageCount);
        facts.setDefectCount(defectCount);
        facts.setCaseCount(caseCount);
        facts.setDefectRate(round4(defectRate));
        facts.setBoxDensity(round4(boxDensity));
        facts.setAvgInferenceMs(round2(avgInferenceMs));
        facts.setHighRiskCount(highRisk == null ? 0 : highRisk.intValue());
        facts.setRuleSeverity(batch.getSeverity() == null ? SeverityRules.LOW : batch.getSeverity());

        // 2. 类别统计(比例 = 该类案例数 / 案例总数)
        List<Map<String, Object>> rawStats = caseMapper.selectClassStats(batchId);
        List<AiReportRequest.ClassFact> classStats = new ArrayList<>(rawStats.size());
        int totalCases = rawStats.stream()
                .mapToInt(m -> toInt(m.get("count"))).sum();
        for (Map<String, Object> m : rawStats) {
            String cn = (String) m.get("className");
            int cnt = toInt(m.get("count"));
            AiReportRequest.ClassFact cf = new AiReportRequest.ClassFact();
            cf.setClassName(cn);
            cf.setClassNameCn(CLASS_NAME_CN.getOrDefault(cn, cn));
            cf.setCount(cnt);
            cf.setRatio(totalCases > 0 ? round4((double) cnt / totalCases) : 0.0);
            cf.setAvgConfidence(toDouble(m.get("avgConfidence")));
            classStats.add(cf);
        }

        // 3. 各类别最高置信代表案例(Milvus 反查历史相似案例的锚点)
        List<Map<String, Object>> rawReps = caseMapper.selectRepresentatives(batchId);
        List<AiReportRequest.RepresentativeCase> representatives = new ArrayList<>(rawReps.size());
        for (Map<String, Object> m : rawReps) {
            String cn = (String) m.get("className");
            String pk = (String) m.get("milvusPk");
            Object rid = m.get("recordId");
            if (cn == null || pk == null || rid == null) {
                continue;
            }
            AiReportRequest.RepresentativeCase rep = new AiReportRequest.RepresentativeCase();
            rep.setClassName(cn);
            rep.setMilvusPk(pk);
            rep.setRecordId(((Number) rid).longValue());
            representatives.add(rep);
        }

        AiReportRequest req = new AiReportRequest();
        req.setBatch(facts);
        req.setClassStats(classStats);
        req.setRepresentatives(representatives);

        // 4. 调 Python /report/generate(LLM 生成 + 证据检索 + Schema 校验合并)
        AiReportResponse resp;
        try {
            resp = aiServiceReportClient.post()
                    .uri("/report/generate")
                    .body(req)
                    .retrieve()
                    .body(AiReportResponse.class);
        } catch (HttpStatusCodeException e) {
            throw new BusinessException(e.getStatusCode().value(),
                    "报告服务: " + extractDetail(e.getResponseBodyAsString()));
        }
        if (resp == null || resp.getReport() == null) {
            throw new BusinessException(502, "报告服务返回空响应");
        }

        // 5. 落库: report_json 原样存最终自洽报告(程序事实+证据+叙述)
        String reportJson;
        try {
            reportJson = objectMapper.writeValueAsString(resp.getReport());
        } catch (Exception e) {
            throw new BusinessException(500, "报告序列化失败: " + e.getMessage());
        }
        batch.setReportJson(reportJson);
        batch.setReportModel(resp.getModel());
        batch.setLlmTokens(resp.getTokens() == null ? null : resp.getTokens().getTotalTokens());
        batch.setReported(1);
        batchMapper.updateById(batch);
        log.info("批次 {} 报告生成完成 model={} tokens={}",
                batchId, resp.getModel(),
                resp.getTokens() == null ? null : resp.getTokens().getTotalTokens());
        return resp.getModel();
    }

    // ==================== 辅助 ====================

    private InspectBatch newBatch(String name, String source, int imageCount, Long userId) {
        InspectBatch batch = new InspectBatch();
        batch.setBatchNo(generateBatchNo(source));
        batch.setName(name);
        batch.setSource(source);
        batch.setStatus("pending");
        batch.setImageCount(imageCount);
        batch.setProcessedCount(0);
        batch.setDefectImageCount(0);
        batch.setDefectCount(0);
        batch.setCaseCount(0);
        batch.setTotalInferenceMs(0.0);
        batch.setReported(0);
        batch.setCreatedBy(userId);
        return batch;
    }

    /** BATCH-yyyyMMdd-HHmmss-xxxx / HIST-...(历史脚本自行指定) */
    private String generateBatchNo(String source) {
        String prefix = "history".equals(source) ? "HIST" : "BATCH";
        return prefix + "-" + LocalDateTime.now().format(BATCH_NO_FMT)
                + "-" + String.format("%04d", ThreadLocalRandom.current().nextInt(10000));
    }

    private void saveRecords(List<InspectRecord> records) {
        for (InspectRecord r : records) {
            recordMapper.insert(r);
        }
    }

    /** 实体 -> 列表行 VO(Controller 创建接口也复用) */
    public BatchVO toBatchVO(InspectBatch b) {
        BatchVO vo = new BatchVO();
        vo.setId(b.getId());
        vo.setBatchNo(b.getBatchNo());
        vo.setName(b.getName());
        vo.setSource(b.getSource());
        vo.setStatus(b.getStatus());
        vo.setModel(b.getModel());
        vo.setImageCount(b.getImageCount());
        vo.setProcessedCount(b.getProcessedCount());
        vo.setDefectImageCount(b.getDefectImageCount());
        vo.setDefectCount(b.getDefectCount());
        vo.setCaseCount(b.getCaseCount());
        vo.setSeverity(b.getSeverity());
        vo.setTotalInferenceMs(b.getTotalInferenceMs());
        vo.setErrorMsg(b.getErrorMsg());
        vo.setReported(b.getReported());
        vo.setCreateTime(b.getCreateTime());
        return vo;
    }

    private void copyBatchFields(InspectBatch b, BatchDetailVO vo) {
        vo.setId(b.getId());
        vo.setBatchNo(b.getBatchNo());
        vo.setName(b.getName());
        vo.setSource(b.getSource());
        vo.setStatus(b.getStatus());
        vo.setModel(b.getModel());
        vo.setImageCount(b.getImageCount());
        vo.setProcessedCount(b.getProcessedCount());
        vo.setDefectImageCount(b.getDefectImageCount());
        vo.setDefectCount(b.getDefectCount());
        vo.setCaseCount(b.getCaseCount());
        vo.setSeverity(b.getSeverity());
        vo.setTotalInferenceMs(b.getTotalInferenceMs());
        vo.setErrorMsg(b.getErrorMsg());
        vo.setReportJson(b.getReportJson());
        vo.setReportModel(b.getReportModel());
        vo.setLlmTokens(b.getLlmTokens());
        vo.setReported(b.getReported());
        vo.setCreateTime(b.getCreateTime());
    }

    private String presignedUrl(String bucket, String objectPath, int hours) {
        if (!StringUtils.hasText(bucket) || !StringUtils.hasText(objectPath)) {
            return null;
        }
        try {
            return presignMinioClient.getPresignedObjectUrl(GetPresignedObjectUrlArgs.builder()
                    .method(Method.GET)
                    .bucket(bucket)
                    .object(objectPath)
                    .expiry(hours, TimeUnit.HOURS)
                    .build());
        } catch (Exception e) {
            log.warn("生成预签名 URL 失败 {}/{}: {}", bucket, objectPath, e.getMessage());
            return null;
        }
    }

    private static String sanitizeFileName(String name) {
        if (!StringUtils.hasText(name)) {
            return "upload.jpg";
        }
        String base = name.replaceAll("[\\\\/]", "_");
        return base.length() > 120 ? base.substring(base.length() - 120) : base;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max);
    }

    /** null 安全的 int 取值 */
    private static int nz(Integer v) {
        return v == null ? 0 : v;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    private static int toInt(Object o) {
        if (o instanceof Number n) {
            return n.intValue();
        }
        return o == null ? 0 : Integer.parseInt(o.toString());
    }

    private static long toLong(Object o) {
        if (o instanceof Number n) {
            return n.longValue();
        }
        return o == null ? 0L : Long.parseLong(o.toString());
    }

    private static double toDouble(Object o) {
        if (o instanceof Number n) {
            return n.doubleValue();
        }
        return o == null ? 0.0 : Double.parseDouble(o.toString());
    }

    private String extractDetail(String json) {
        try {
            Map<?, ?> map = objectMapper.readValue(json, Map.class);
            Object detail = map.get("detail");
            return detail != null ? detail.toString() : json;
        } catch (Exception ignore) {
            return json;
        }
    }
}

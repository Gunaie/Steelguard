package com.steelguard.admin.inference.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.steelguard.admin.inference.dto.DetectResponse;
import com.steelguard.admin.inference.dto.VlDetectResponse;
import com.steelguard.common.exception.BusinessException;
import com.steelguard.common.result.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpEntity;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Map;

/**
 * 推理网关: 转发到 Python AI 服务
 * 阶段0: ping 探活; 阶段3: YOLO 图片检测 multipart 透传
 */
@Slf4j
@Tag(name = "推理网关")
@RestController
@RequestMapping("/inference")
public class InferenceController {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RestClient aiServiceClient;
    private final RestClient aiServiceVlClient;

    public InferenceController(
            @Qualifier("aiServiceClient") RestClient aiServiceClient,
            @Qualifier("aiServiceVlClient") RestClient aiServiceVlClient) {
        this.aiServiceClient = aiServiceClient;
        this.aiServiceVlClient = aiServiceVlClient;
    }

    @Operation(summary = "探活 AI 服务(验证 Java->Python 互通)")
    @GetMapping("/ping-ai")
    public Result<Map> pingAi() {
        Map result = aiServiceClient.get()
                .uri("/health")
                .retrieve()
                .body(Map.class);
        return Result.ok(result);
    }

    @Operation(summary = "上传钢材图片做 YOLO 缺陷检测(转发 Python GPU 推理)")
    @PostMapping(value = "/detect", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<DetectResponse> detect(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "conf", required = false) Double conf,
            @RequestParam(value = "iou", required = false) Double iou) throws IOException {

        if (file.isEmpty()) {
            throw new BusinessException(400, "上传文件为空");
        }

        // 组装 multipart: 图片字节沿用原文件名/类型, 阈值作为表单字段
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        MediaType fileType = MediaType.APPLICATION_OCTET_STREAM;
        if (file.getContentType() != null) {
            fileType = MediaType.parseMediaType(file.getContentType());
        }
        String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "upload.jpg";
        builder.part("file", file.getResource()).contentType(fileType).filename(filename);
        if (conf != null) {
            builder.part("conf", String.valueOf(conf));
        }
        if (iou != null) {
            builder.part("iou", String.valueOf(iou));
        }
        MultiValueMap<String, HttpEntity<?>> body = builder.build();

        try {
            DetectResponse resp = aiServiceClient.post()
                    .uri("/infer/detect")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(DetectResponse.class);
            return Result.ok(resp);
        } catch (HttpStatusCodeException e) {
            // Python 侧 FastAPI 错误体形如 {"detail": "..."}
            String detail = extractDetail(e.getResponseBodyAsString());
            log.warn("AI 推理服务返回错误 {}: {}", e.getStatusCode().value(), detail);
            throw new BusinessException(e.getStatusCode().value(), "AI 服务: " + detail);
        }
    }

    @Operation(summary = "上传钢材图片做 Qwen-VL 零样本缺陷检测(转发 Python 视觉大模型)")
    @PostMapping(value = "/detect-vl", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<VlDetectResponse> detectVl(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "model", required = false) String model) throws IOException {

        if (file.isEmpty()) {
            throw new BusinessException(400, "上传文件为空");
        }

        // 组装 multipart: model 可选(plus/max/具体模型 id), 为空时 Python 侧走默认 qwen-vl-plus
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        MediaType fileType = MediaType.APPLICATION_OCTET_STREAM;
        if (file.getContentType() != null) {
            fileType = MediaType.parseMediaType(file.getContentType());
        }
        String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "upload.jpg";
        builder.part("file", file.getResource()).contentType(fileType).filename(filename);
        if (model != null && !model.isBlank()) {
            builder.part("model", model.trim());
        }
        MultiValueMap<String, HttpEntity<?>> body = builder.build();

        try {
            VlDetectResponse resp = aiServiceVlClient.post()
                    .uri("/infer/detect-vl")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(VlDetectResponse.class);
            return Result.ok(resp);
        } catch (HttpStatusCodeException e) {
            // Python 侧 FastAPI 错误体形如 {"detail": "..."}
            String detail = extractDetail(e.getResponseBodyAsString());
            log.warn("视觉大模型服务返回错误 {}: {}", e.getStatusCode().value(), detail);
            throw new BusinessException(e.getStatusCode().value(), "AI 服务: " + detail);
        }
    }

    private String extractDetail(String json) {
        try {
            Map<?, ?> map = OBJECT_MAPPER.readValue(json, Map.class);
            Object detail = map.get("detail");
            return detail != null ? detail.toString() : json;
        } catch (Exception ignore) {
            return json;
        }
    }
}

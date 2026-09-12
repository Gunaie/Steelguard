package com.steelguard.admin.inspection.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
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
 * 缺陷溯源网关: 以图搜图 + 向量库统计, 转发 Python /trace/*
 */
@Slf4j
@Tag(name = "缺陷溯源")
@RestController
@RequestMapping("/trace")
public class TraceController {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RestClient aiServiceTraceClient;

    public TraceController(@Qualifier("aiServiceTraceClient") RestClient aiServiceTraceClient) {
        this.aiServiceTraceClient = aiServiceTraceClient;
    }

    @Operation(summary = "以图搜图: 上传图片(可带 bbox)检索历史相似缺陷")
    @PostMapping(value = "/search", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<Map> search(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "bbox", required = false) String bbox,
            @RequestParam(value = "class_name", required = false) String className,
            @RequestParam(value = "top_k", required = false) Integer topK,
            @RequestParam(value = "exclude_record_id", required = false) Long excludeRecordId)
            throws IOException {

        if (file.isEmpty()) {
            throw new BusinessException(400, "上传文件为空");
        }
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        MediaType fileType = MediaType.APPLICATION_OCTET_STREAM;
        if (file.getContentType() != null) {
            fileType = MediaType.parseMediaType(file.getContentType());
        }
        String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "query.jpg";
        builder.part("file", file.getResource()).contentType(fileType).filename(filename);
        if (bbox != null && !bbox.isBlank()) {
            builder.part("bbox", bbox);
        }
        if (className != null && !className.isBlank()) {
            builder.part("class_name", className.trim());
        }
        if (topK != null) {
            builder.part("top_k", String.valueOf(topK));
        }
        if (excludeRecordId != null) {
            builder.part("exclude_record_id", String.valueOf(excludeRecordId));
        }
        MultiValueMap<String, HttpEntity<?>> body = builder.build();

        try {
            Map resp = aiServiceTraceClient.post()
                    .uri("/trace/search")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(Map.class);
            return Result.ok(resp);
        } catch (HttpStatusCodeException e) {
            String detail = extractDetail(e.getResponseBodyAsString());
            log.warn("溯源服务返回错误 {}: {}", e.getStatusCode().value(), detail);
            throw new BusinessException(e.getStatusCode().value(), "AI 服务: " + detail);
        }
    }

    @Operation(summary = "向量库统计(案例总数/类别分布)")
    @GetMapping("/stats")
    public Result<Map> stats() {
        try {
            Map resp = aiServiceTraceClient.get()
                    .uri("/trace/stats")
                    .retrieve()
                    .body(Map.class);
            return Result.ok(resp);
        } catch (HttpStatusCodeException e) {
            throw new BusinessException(e.getStatusCode().value(),
                    "AI 服务: " + extractDetail(e.getResponseBodyAsString()));
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

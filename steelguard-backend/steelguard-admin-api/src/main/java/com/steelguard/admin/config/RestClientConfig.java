package com.steelguard.admin.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * RestClient 配置 (调 Python AI 服务)
 */
@Configuration
public class RestClientConfig {

    @Value("${steelguard.ai-service.base-url}")
    private String aiServiceBaseUrl;

    @Bean
    public RestClient aiServiceClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(60000); // AI 推理较慢
        return RestClient.builder()
                .baseUrl(aiServiceBaseUrl)
                .requestFactory(factory)
                .build();
    }

    /**
     * 视觉大模型专用客户端: 云端 Qwen-VL 存在 60s+ 长尾(Python 侧还有一次重试),
     * 读超时放宽到 180s, 避免网关侧提前 504
     */
    @Bean("aiServiceVlClient")
    public RestClient aiServiceVlClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(180000);
        return RestClient.builder()
                .baseUrl(aiServiceBaseUrl)
                .requestFactory(factory)
                .build();
    }

    /**
     * 溯源链路专用客户端: /trace/index 首次调用需加载 ResNet50 + 裁剪上传,
     * 读超时放宽到 120s
     */
    @Bean("aiServiceTraceClient")
    public RestClient aiServiceTraceClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(120000);
        return RestClient.builder()
                .baseUrl(aiServiceBaseUrl)
                .requestFactory(factory)
                .build();
    }

    /**
     * LLM 结构化报告专用客户端: qwen-plus 生成 + Milvus 相似案例检索,
     * 读超时放宽到 180s(云端 LLM 存在长尾)
     */
    @Bean("aiServiceReportClient")
    public RestClient aiServiceReportClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(180000);
        return RestClient.builder()
                .baseUrl(aiServiceBaseUrl)
                .requestFactory(factory)
                .build();
    }
}

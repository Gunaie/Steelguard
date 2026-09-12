package com.steelguard.admin.config;

import io.minio.MinioClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * MinIO 客户端配置
 *
 * 容器化双端点设计:
 * - {@code minioClient}: 内部端点, 用于实际上传/下载 I/O(如 http://minio:9000)
 * - {@code presignMinioClient}: 对外端点, 仅用于离线生成预签名 URL(浏览器需可达,
 *   如 http://host.docker.internal:9000)。预签名只做本地签名计算, 不产生网络请求,
 *   因此两个客户端可以指向不同主机名, 且签名对最终访问地址生效。
 * 非容器环境不配置 public-endpoint 时, 两者均指向同一地址, 行为与历史一致。
 */
@Configuration
public class MinioConfig {

    @Bean
    public MinioClient minioClient(
            @Value("${minio.endpoint}") String endpoint,
            @Value("${minio.access-key}") String accessKey,
            @Value("${minio.secret-key}") String secretKey) {
        return MinioClient.builder()
                .endpoint(endpoint)
                .credentials(accessKey, secretKey)
                .build();
    }

    @Bean
    public MinioClient presignMinioClient(
            @Value("${minio.public-endpoint}") String publicEndpoint,
            @Value("${minio.access-key}") String accessKey,
            @Value("${minio.secret-key}") String secretKey) {
        return MinioClient.builder()
                .endpoint(publicEndpoint)
                .credentials(accessKey, secretKey)
                .build();
    }
}

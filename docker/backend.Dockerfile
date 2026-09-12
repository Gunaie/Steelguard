# syntax=docker/dockerfile:1
# ==========================================================================
# SteelGuard 后端镜像(Spring Boot fat jar)
# 构建上下文: steelguard-backend/ (compose 已配置)
# 多阶段: Maven 构建(阿里云镜像) -> JRE17 运行
# ==========================================================================

# ---------- 构建阶段 ----------
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build

# Maven 阿里云镜像(内联 settings, 避免污染模块目录)
RUN mkdir -p /root/.m2 && cat > /root/.m2/settings.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
  <mirrors>
    <mirror>
      <id>aliyun-public</id>
      <name>Aliyun Public Mirror</name>
      <url>https://maven.aliyun.com/repository/public</url>
      <mirrorOf>*</mirrorOf>
    </mirror>
  </mirrors>
</settings>
EOF

# 先拷 POM 预热依赖层(两模块)
COPY pom.xml ./
COPY steelguard-common/pom.xml ./steelguard-common/pom.xml
COPY steelguard-admin-api/pom.xml ./steelguard-admin-api/pom.xml
# 本项目父 POM 未做依赖收敛分层, 首次仍需源码才能 package; 直接拷全量源码构建
COPY steelguard-common ./steelguard-common
COPY steelguard-admin-api ./steelguard-admin-api
RUN mvn -B clean package -DskipTests \
    && ls -lh steelguard-admin-api/target/steelguard-admin-api.jar

# ---------- 运行阶段 ----------
FROM eclipse-temurin:17-jre-jammy
WORKDIR /app

ENV TZ=Asia/Shanghai \
    JAVA_OPTS=""

COPY --from=build /build/steelguard-admin-api/target/steelguard-admin-api.jar /app/steelguard-admin-api.jar

EXPOSE 8080

# temurin jre 镜像不含 curl/wget, 用 bash 内置 /dev/tcp 探活
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080 && echo -e "GET /api/ping HTTP/1.0\r\n\r\n" >&3' || exit 1

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/steelguard-admin-api.jar"]

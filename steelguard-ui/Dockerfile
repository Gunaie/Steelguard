# syntax=docker/dockerfile:1
# ==========================================================================
# SteelGuard 前端镜像: Vite 构建 -> nginx 托管静态资源 + /api 反代后端
# 构建上下文: steelguard-ui/
# ==========================================================================

# ---------- 构建阶段 ----------
FROM node:22-alpine AS build
WORKDIR /app

# npmmirror 国内加速
RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------- 运行阶段 ----------
FROM nginx:1.27-alpine
ENV TZ=Asia/Shanghai

# 静态资源 + SPA fallback + /api 反代
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]

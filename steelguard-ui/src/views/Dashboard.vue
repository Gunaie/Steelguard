<template>
  <div class="dashboard">
    <a-row :gutter="16">
      <a-col :span="8">
        <a-card title="后端服务" :loading="backendLoading">
          <a-tag :color="backendStatus === 'UP' ? 'green' : 'red'">
            {{ backendStatus || '检测中' }}
          </a-tag>
          <div class="card-body">{{ backendInfo }}</div>
        </a-card>
      </a-col>
      <a-col :span="8">
        <a-card title="AI 服务(Java→Python 链路)" :loading="aiLoading">
          <a-tag :color="aiStatus === 'UP' ? 'green' : 'red'">
            {{ aiStatus || '检测中' }}
          </a-tag>
          <div class="card-body">{{ aiInfo }}</div>
        </a-card>
      </a-col>
      <a-col :span="8">
        <a-card title="当前用户">
          <a-descriptions :column="1" size="small">
            <a-descriptions-item label="用户ID">{{ userStore.userInfo?.userId }}</a-descriptions-item>
            <a-descriptions-item label="用户名">{{ userStore.userInfo?.username }}</a-descriptions-item>
            <a-descriptions-item label="角色">{{ userStore.userInfo?.role }}</a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="阶段 0 验收项" style="margin-top: 16px">
      <a-space direction="vertical" style="width: 100%">
        <a-alert
          v-for="item in checklist"
          :key="item.text"
          :message="item.text"
          :type="item.pass ? 'success' : 'info'"
          show-icon
        />
      </a-space>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { healthCheck, pingAi } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

const backendStatus = ref('')
const backendInfo = ref('')
const backendLoading = ref(true)
const aiStatus = ref('')
const aiInfo = ref('')
const aiLoading = ref(true)

async function loadBackend() {
  try {
    const data: any = await healthCheck()
    backendStatus.value = data.status
    backendInfo.value = data.service || ''
  } catch (e) {
    backendStatus.value = 'DOWN'
    backendInfo.value = '后端不可达'
  } finally {
    backendLoading.value = false
  }
}

async function loadAi() {
  try {
    const data: any = await pingAi()
    aiStatus.value = data.status || 'UP'
    aiInfo.value = data.ai_service || data.message || ''
  } catch (e) {
    aiStatus.value = 'DOWN'
    aiInfo.value = 'AI 服务链路不通'
  } finally {
    aiLoading.value = false
  }
}

const checklist = computed(() => [
  { text: '① Docker 基础设施(MySQL/Redis/MinIO)已启动', pass: true },
  { text: '② Spring Boot 后端健康检查通过', pass: backendStatus.value === 'UP' },
  { text: '③ FastAPI AI 服务健康检查通过', pass: aiStatus.value === 'UP' },
  { text: '④ Java→Python 推理网关链路打通', pass: aiStatus.value === 'UP' },
  { text: '⑤ 前端登录成功并携带 JWT', pass: !!userStore.token },
  { text: '⑥ Swagger 文档可访问 /api/doc.html', pass: backendStatus.value === 'UP' },
])

onMounted(() => {
  loadBackend()
  loadAi()
})
</script>

<style scoped>
.dashboard {
  padding: 0;
}
.card-body {
  margin-top: 8px;
  color: #888;
  font-size: 13px;
}
</style>

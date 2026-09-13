<template>
  <a-layout style="min-height: 100vh">
    <a-layout-sider v-model:collapsed="collapsed" collapsible>
      <div class="logo">{{ collapsed ? 'SG' : 'SteelGuard' }}</div>
      <a-menu
        v-model:selectedKeys="selectedKeys"
        theme="dark"
        mode="inline"
        @click="onMenuClick"
      >
        <a-menu-item key="/dashboard">
          <DashboardOutlined />
          <span>工作台</span>
        </a-menu-item>
        <a-menu-item key="/dataset">
          <DatabaseOutlined />
          <span>数据集</span>
        </a-menu-item>
        <a-menu-item key="/infer">
          <ScanOutlined />
          <span>缺陷检测</span>
        </a-menu-item>
        <a-menu-item key="/inspection/batches">
          <ProfileOutlined />
          <span>质检批次</span>
        </a-menu-item>
        <a-menu-item key="/trend">
          <LineChartOutlined />
          <span>缺陷趋势</span>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout>
      <a-layout-header style="background: #fff; padding: 0 16px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 600">SteelGuard AI 质检平台</span>
        <a-space>
          <span>{{ userStore.userInfo?.nickname || userStore.userInfo?.username }}</span>
          <a-button type="link" @click="handleLogout">退出</a-button>
        </a-space>
      </a-layout-header>
      <a-layout-content style="margin: 16px">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  DashboardOutlined,
  DatabaseOutlined,
  LineChartOutlined,
  ProfileOutlined,
  ScanOutlined,
} from '@ant-design/icons-vue'
import { useUserStore } from '@/stores/user'
import { logout as logoutApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

/** 报告详情等子路由也高亮「质检批次」菜单 */
function resolveSelected(path: string): string {
  if (path.startsWith('/inspection/batches')) return '/inspection/batches'
  return path
}

const collapsed = ref(false)
const selectedKeys = ref<string[]>([resolveSelected(route.path)])

watch(route, (r) => {
  selectedKeys.value = [resolveSelected(r.path)]
})

function onMenuClick({ key }: { key: string }) {
  if (key && key !== route.path) {
    router.push(key)
  }
}

async function handleLogout() {
  // 服务端撤销 token(Redis 黑名单); 网络失败不阻塞本地清理
  try {
    await logoutApi()
  } catch {
    // ignore: 本地仍需退出登录态
  }
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.logo {
  height: 48px;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  text-align: center;
  line-height: 48px;
  border-bottom: 1px solid #002140;
}
</style>

<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <h1>SteelGuard</h1>
        <p>AI 钢材表面缺陷智能质检平台</p>
      </div>
      <a-form :model="form" layout="vertical" @finish="handleLogin">
        <a-form-item label="用户名" name="username" :rules="[{ required: true, message: '请输入用户名' }]">
          <a-input v-model:value="form.username" placeholder="admin" size="large">
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="密码" name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="form.password" placeholder="steel123" size="large" @pressEnter="handleLogin">
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>
        <a-form-item>
          <a-button type="primary" html-type="submit" size="large" block :loading="loading">
            登 录
          </a-button>
        </a-form-item>
        <div class="login-tip">默认账号: admin / steel123</div>
      </a-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined } from '@ant-design/icons-vue'
import { login } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)

const form = reactive({
  username: 'admin',
  password: 'steel123',
})

async function handleLogin() {
  loading.value = true
  try {
    const data = await login(form)
    userStore.setLogin(data)
    message.success('登录成功')
    router.push('/dashboard')
  } catch (e) {
    // 错误已在拦截器处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a2a6c, #b21f1f, #fdbb2d);
  background-size: 200% 200%;
  animation: gradient 12s ease infinite;
}
@keyframes gradient {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.login-box {
  width: 380px;
  padding: 40px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
}
.login-header {
  text-align: center;
  margin-bottom: 28px;
}
.login-header h1 {
  margin: 0;
  font-size: 28px;
  color: #1a2a6c;
  letter-spacing: 2px;
}
.login-header p {
  margin: 8px 0 0;
  color: #888;
  font-size: 13px;
}
.login-tip {
  text-align: center;
  color: #aaa;
  font-size: 12px;
}
</style>

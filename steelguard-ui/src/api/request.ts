import axios from 'axios'
import { message } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'
import router from '@/router'

const request = axios.create({
  baseURL: '/api', // 走 vite 代理
  timeout: 30000,
})

// 请求拦截: 带 token
request.interceptors.request.use((config) => {
  const userStore = useUserStore()
  if (userStore.token) {
    config.headers.Authorization = `Bearer ${userStore.token}`
  }
  return config
})

// 响应拦截: 统一处理
request.interceptors.response.use(
  (response) => {
    const res = response.data
    if (res.code === 200) {
      return res.data
    }
    message.error(res.message || '请求失败')
    return Promise.reject(new Error(res.message || '请求失败'))
  },
  (error) => {
    if (error.response?.status === 401) {
      const userStore = useUserStore()
      userStore.logout()
      router.push('/login')
      message.error('登录已过期, 请重新登录')
    } else {
      message.error(error.response?.data?.message || error.message || '网络异常')
    }
    return Promise.reject(error)
  }
)

export default request

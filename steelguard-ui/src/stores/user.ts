import { defineStore } from 'pinia'
import { ref } from 'vue'

const TOKEN_KEY = 'steelguard_token'
const USER_KEY = 'steelguard_user'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const userInfo = ref<any>(
    localStorage.getItem(USER_KEY) ? JSON.parse(localStorage.getItem(USER_KEY)!) : null
  )

  function setLogin(data: {
    token: string
    userId: number
    username: string
    nickname?: string
    role?: string
  }) {
    token.value = data.token
    userInfo.value = data
    localStorage.setItem(TOKEN_KEY, data.token)
    localStorage.setItem(USER_KEY, JSON.stringify(data))
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, userInfo, setLogin, logout }
})

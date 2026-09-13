import request from './request'

export interface LoginParams {
  username: string
  password: string
}

export interface LoginResult {
  token: string
  tokenType: string
  userId: number
  username: string
  nickname?: string
  role?: string
}

// 登录
export function login(data: LoginParams) {
  return request.post<any, LoginResult>('/auth/login', data)
}

// 注册
export function register(data: { username: string; password: string; nickname?: string }) {
  return request.post<any, number>('/auth/register', data)
}

// 登出(服务端将 token 加入 Redis 黑名单)
export function logout() {
  return request.post<any, void>('/auth/logout')
}

// 健康检查
export function healthCheck() {
  return request.get<any, any>('/health')
}

// 探活 AI 服务 (Java->Python)
export function pingAi() {
  return request.get<any, any>('/inference/ping-ai')
}

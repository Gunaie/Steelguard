import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/',
      component: () => import('@/layouts/BasicLayout.vue'),
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('@/views/Dashboard.vue'),
          meta: { title: '工作台', requiresAuth: true },
        },
        {
          path: 'dataset',
          name: 'Dataset',
          component: () => import('@/views/dataset/Dataset.vue'),
          meta: { title: '数据集', requiresAuth: true },
        },
        {
          path: 'infer',
          name: 'Infer',
          component: () => import('@/views/inference/Infer.vue'),
          meta: { title: '缺陷检测', requiresAuth: true },
        },
        {
          path: 'inspection/batches',
          name: 'BatchList',
          component: () => import('@/views/inspection/BatchList.vue'),
          meta: { title: '质检批次', requiresAuth: true },
        },
        {
          path: 'inspection/batches/:id/report',
          name: 'ReportDetail',
          component: () => import('@/views/inspection/ReportDetail.vue'),
          meta: { title: '质检报告', requiresAuth: true },
        },
        {
          path: 'trend',
          name: 'DefectTrend',
          component: () => import('@/views/dashboard/DefectTrend.vue'),
          meta: { title: '缺陷趋势', requiresAuth: true },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  if (to.meta.requiresAuth && !userStore.token) {
    next('/login')
  } else if (to.path === '/login' && userStore.token) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router

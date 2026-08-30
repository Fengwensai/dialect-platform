import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'

const routes = [
  { path: '/login', name: 'login', component: Login },
  {
    path: '/',
    component: () => import('../layout/AdminLayout.vue'),
    redirect: '/words',
    children: [
      { path: 'excel', name: 'excel', component: () => import('../views/ExcelImport.vue'), meta: { title: '词表导入' } },
      { path: 'words', name: 'words', component: () => import('../views/WordLibrary.vue'), meta: { title: '词条管理' } },
      { path: 'tasks', name: 'tasks', component: () => import('../views/TaskAssign.vue'), meta: { title: '任务分配' } },
      { path: 'tasks/:id', name: 'taskDetail', component: () => import('../views/TaskDetail.vue'), meta: { title: '任务详情', activeMenu: '/tasks' } },
      { path: 'review', name: 'review', component: () => import('../views/ReviewRecordings.vue'), meta: { title: '录音审核' } },
      { path: 'speakers', name: 'speakers', component: () => import('../views/Speakers.vue'), meta: { title: '发音人管理' } },
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '数据看板' } },
      { path: 'teams', name: 'teams', component: () => import('../views/TeamManage.vue'), meta: { title: '团队管理' } },
      { path: 'regions', name: 'regions', component: () => import('../views/RegionView.vue'), meta: { title: '行政区划' } },
      { path: 'agreements', name: 'agreements', component: () => import('../views/AgreementManage.vue'), meta: { title: '协议管理', superOnly: true } },
      { path: 'users', name: 'users', component: () => import('../views/UserManage.vue'), meta: { title: '管理员管理', superOnly: true } },
      { path: 'audit-logs', name: 'auditLogs', component: () => import('../views/AuditLog.vue'), meta: { title: '审计日志', superOnly: true } },
      { path: 'data-health', name: 'dataHealth', component: () => import('../views/DataHealth.vue'), meta: { title: '数据健康', superOnly: true } }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  const admin = JSON.parse(localStorage.getItem('admin') || 'null')
  if (to.path !== '/login' && !token) return '/login'
  if (to.path === '/login' && token) return '/'
  if (to.meta.superOnly && admin?.role !== 'super_admin') return '/words'
})

export default router

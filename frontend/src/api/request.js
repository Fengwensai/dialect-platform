import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status
    const detail = err.response?.data?.detail
    if (status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('admin')
      if (router.currentRoute.value.path !== '/login') {
        router.push('/login')
      }
      ElMessage.error(detail || '登录已过期，请重新登录')
    } else if (status === 403) {
      ElMessage.error(detail || '没有权限执行此操作')
    } else {
      ElMessage.error(detail || '请求失败，请稍后重试')
    }
    return Promise.reject(err)
  }
)

export default request

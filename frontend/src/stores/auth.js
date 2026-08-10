import { defineStore } from 'pinia'
import request from '../api/request'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    admin: JSON.parse(localStorage.getItem('admin') || 'null')
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    isSuper: (s) => s.admin?.role === 'super_admin',
    roleLabel: (s) => (s.admin?.role === 'super_admin' ? '超级管理员' : '省管理员'),
    provinceCode: (s) => s.admin?.province_code || ''
  },
  actions: {
    async login(username, password) {
      const data = await request.post('/auth/login', { username, password })
      this.token = data.access_token
      this.admin = data.admin
      localStorage.setItem('token', this.token)
      localStorage.setItem('admin', JSON.stringify(this.admin))
    },
    logout() {
      this.token = ''
      this.admin = null
      localStorage.removeItem('token')
      localStorage.removeItem('admin')
    }
  }
})

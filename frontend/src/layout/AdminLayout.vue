<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">🗣️ 方言采集平台</div>
      <el-menu :default-active="$route.path" router class="menu" background-color="#1d2b3a" text-color="#c8d0da" active-text-color="#409eff">
        <el-menu-item index="/excel"><el-icon><Upload /></el-icon><span>词表导入</span></el-menu-item>
        <el-menu-item index="/words"><el-icon><Notebook /></el-icon><span>词条管理</span></el-menu-item>
        <el-menu-item index="/tasks"><el-icon><Promotion /></el-icon><span>任务分配</span></el-menu-item>
        <el-menu-item index="/review"><el-icon><Headset /></el-icon><span>录音审核</span></el-menu-item>
        <el-menu-item index="/speakers"><el-icon><Avatar /></el-icon><span>发音人管理</span></el-menu-item>
        <el-menu-item index="/dashboard"><el-icon><DataAnalysis /></el-icon><span>数据看板</span></el-menu-item>
        <el-menu-item index="/teams"><el-icon><Connection /></el-icon><span>团队管理</span></el-menu-item>
        <el-menu-item index="/regions"><el-icon><LocationInformation /></el-icon><span>行政区划</span></el-menu-item>
        <el-menu-item v-if="auth.isSuper" index="/agreements"><el-icon><Document /></el-icon><span>协议管理</span></el-menu-item>
        <el-menu-item v-if="auth.isSuper" index="/users"><el-icon><User /></el-icon><span>管理员管理</span></el-menu-item>
        <el-menu-item v-if="auth.isSuper" index="/audit-logs"><el-icon><Tickets /></el-icon><span>审计日志</span></el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="page-title">{{ $route.meta.title }}</span>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-icon><UserFilled /></el-icon>
            {{ auth.admin?.name || auth.admin?.username }}（{{ auth.roleLabel }}）
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

function onCommand(cmd) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background-color: #1d2b3a;
  overflow: hidden;
}
.logo {
  color: #fff;
  font-size: 17px;
  font-weight: 600;
  text-align: center;
  line-height: 60px;
  background-color: #16232f;
}
.menu {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8eaec;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
}
.user {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #333;
}
.main {
  background: #f5f6f8;
}
</style>

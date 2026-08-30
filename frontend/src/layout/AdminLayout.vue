<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <span class="logo-mark"><el-icon :size="18" color="#fff"><Microphone /></el-icon></span>
        <span class="logo-text">方言采集平台</span>
      </div>
      <div class="logo-line"></div>
      <el-menu :default-active="activeMenu" router class="menu">
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
        <el-menu-item v-if="auth.isSuper" index="/data-health"><el-icon><FirstAidKit /></el-icon><span>数据健康</span></el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="page-title">{{ $route.meta.title }}</span>
        <el-dropdown @command="onCommand">
          <span class="user">
            <span class="user-avatar"><el-icon :size="14"><UserFilled /></el-icon></span>
            <span class="user-name">{{ auth.admin?.name || auth.admin?.username }}</span>
            <span class="user-role">{{ auth.roleLabel }}</span>
            <el-icon class="user-caret"><ArrowDown /></el-icon>
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
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 详情类子页面（如 /tasks/:id）通过 meta.activeMenu 保持父菜单高亮
const activeMenu = computed(() => route.meta.activeMenu || route.path)

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
  background: var(--el-bg-color-page);
}

/* —— 侧栏：深蓝渐变 + 底部微弱青色光 —— */
.aside {
  position: relative;
  background: linear-gradient(180deg, #12233a 0%, #1d2b3a 100%);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
}
.aside::after {
  content: "";
  position: absolute;
  left: -70px; bottom: -90px;
  width: 260px; height: 260px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(0, 201, 176, 0.14), transparent 70%);
  pointer-events: none;
}

/* —— Logo —— */
.logo {
  position: relative;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.logo-mark {
  width: 30px; height: 30px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #409eff, #00c9b0);
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.logo-text {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 2px;
  background: linear-gradient(90deg, #ffffff 20%, #bcd6ff 60%, #8fd8ff 100%);
  -webkit-background-clip: text;
          background-clip: text;
  color: transparent;
}
.logo-line {
  height: 1px;
  margin: 0 18px 8px;
  background: linear-gradient(90deg, transparent, rgba(64, 158, 255, 0.5), rgba(0, 201, 176, 0.5), transparent);
}

/* —— 菜单：圆角胶囊 + 渐变激活条 —— */
.menu {
  border-right: none;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #b9c6d6;
  --el-menu-active-color: #fff;
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.06);
}
.menu :deep(.el-menu-item) {
  height: 48px;
  margin: 3px 10px;
  border-radius: 10px;
}
.menu :deep(.el-menu-item:hover) { color: #fff; }
.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.30), rgba(0, 201, 176, 0.14));
  position: relative;
}
.menu :deep(.el-menu-item.is-active)::before {
  content: "";
  position: absolute;
  left: 0; top: 9px; bottom: 9px;
  width: 3px;
  border-radius: 3px;
  background: linear-gradient(180deg, #409eff, #00c9b0);
}
.menu :deep(.el-menu-item .el-icon) { font-size: 17px; }

/* —— 顶栏：深色玻璃 —— */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 24px;
  background: linear-gradient(180deg, rgba(20, 31, 48, 0.9), rgba(20, 31, 48, 0.7));
  -webkit-backdrop-filter: blur(12px);
          backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.page-title {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--el-text-color-primary);
}
.page-title::before {
  content: "";
  display: inline-block;
  width: 4px; height: 16px;
  margin-right: 10px;
  border-radius: 2px;
  vertical-align: -2px;
  background: linear-gradient(180deg, #409eff, #00c9b0);
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 10px;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: background 0.2s, border-color 0.2s;
}
.user:hover {
  background: rgba(255, 255, 255, 0.09);
  border-color: rgba(255, 255, 255, 0.16);
}
.user-avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #409eff, #00c9b0);
  color: #fff;
}
.user-name { font-size: 14px; color: var(--el-text-color-primary); }
.user-role {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 999px;
  color: #8fd8ff;
  background: rgba(64, 158, 255, 0.16);
}
.user-caret { color: var(--el-text-color-secondary); font-size: 12px; }

/* —— 内容区：深色底 + 与登录页呼应的极光径向光（很淡，不干扰数据） —— */
.main {
  padding: 20px;
  background:
    radial-gradient(900px 500px at 12% -10%, rgba(64, 158, 255, 0.07), transparent 60%),
    radial-gradient(800px 460px at 100% 110%, rgba(0, 201, 176, 0.06), transparent 60%),
    var(--el-bg-color-page);
}
</style>

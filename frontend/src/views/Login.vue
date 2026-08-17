<template>
  <div class="login-wrap">
    <!-- 背景装饰：网格 + 极光光晕 + 音波 -->
    <div class="bg-grid" aria-hidden="true"></div>
    <div class="bg-orb orb-a" aria-hidden="true"></div>
    <div class="bg-orb orb-b" aria-hidden="true"></div>
    <div class="bg-orb orb-c" aria-hidden="true"></div>
    <div class="bg-wave" aria-hidden="true">
      <span
        v-for="b in bars"
        :key="b.i"
        :style="{ height: b.h + 'px', animationDuration: b.s + 's', animationDelay: b.d + 's' }"
      ></span>
    </div>

    <div class="login-card">
      <div class="logo-mark">
        <el-icon :size="26" color="#fff"><Microphone /></el-icon>
      </div>
      <span class="badge">管 理 后 台</span>
      <h2>方言采集平台</h2>
      <p class="en">DIALECT COLLECTION PLATFORM</p>
      <span class="divider"></span>
      <p class="sub">词表导入 · 任务分配 · 审核导出</p>

      <el-form :model="form" :rules="rules" ref="formRef" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名" size="large" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" size="large" show-password :prefix-icon="Lock" />
        </el-form-item>
        <el-button type="primary" size="large" class="btn" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>
    </div>

    <p class="page-foot">© 2026 方言采集平台 · 管理后台</p>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Microphone } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

// 底部音波：每根音柱固定高度 / 时长 / 延迟（确定性取值，避免刷新跳动）
const bars = Array.from({ length: 44 }, (_, i) => ({
  i,
  h: 16 + ((i * 37) % 62),
  d: (i % 7) * 0.16,
  s: 1.2 + ((i * 53) % 28) / 18
}))

async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push('/words')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  overflow: hidden;
  background:
    radial-gradient(1100px 700px at 18% 8%, rgba(64, 158, 255, 0.20), transparent 62%),
    radial-gradient(1000px 680px at 88% 92%, rgba(0, 201, 176, 0.16), transparent 60%),
    radial-gradient(900px 600px at 50% 60%, rgba(120, 110, 255, 0.10), transparent 65%),
    linear-gradient(160deg, #0a1220 0%, #12233a 48%, #1d2b3a 100%);
}

/* —— 背景网格 —— */
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
  background-size: 56px 56px;
  -webkit-mask-image: radial-gradient(ellipse at 50% 38%, #000 25%, transparent 78%);
          mask-image: radial-gradient(ellipse at 50% 38%, #000 25%, transparent 78%);
}

/* —— 极光光晕 —— */
.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  will-change: transform;
}
.orb-a {
  width: 520px; height: 520px;
  left: -120px; top: -140px;
  background: rgba(64, 158, 255, 0.30);
  animation: driftA 26s ease-in-out infinite;
}
.orb-b {
  width: 460px; height: 460px;
  right: -100px; bottom: -120px;
  background: rgba(0, 201, 176, 0.22);
  animation: driftB 30s ease-in-out infinite;
}
.orb-c {
  width: 320px; height: 320px;
  left: 50%; top: 46%;
  margin-left: -160px; margin-top: -160px;
  background: rgba(120, 110, 255, 0.18);
  animation: driftC 22s ease-in-out infinite;
}
@keyframes driftA {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50%      { transform: translate(60px, -40px) scale(1.1); }
}
@keyframes driftB {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50%      { transform: translate(-50px, 30px) scale(1.08); }
}
@keyframes driftC {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33%      { transform: translate(30px, 40px) scale(1.05); }
  66%      { transform: translate(-30px, -20px) scale(0.96); }
}

/* —— 底部音波律动（呼应“方言=声音”） —— */
.bg-wave {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 140px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 6px;
  padding: 0 24px;
  opacity: 0.55;
  pointer-events: none;
  -webkit-mask-image: linear-gradient(180deg, transparent, #000 55%, #000);
          mask-image: linear-gradient(180deg, transparent, #000 55%, #000);
}
.bg-wave span {
  flex: none;
  width: 3px;
  border-radius: 3px 3px 0 0;
  transform-origin: bottom;
  background: linear-gradient(180deg, rgba(64, 158, 255, 0), rgba(64, 158, 255, 0.9));
  animation: wavebar 2s ease-in-out infinite;
}
@keyframes wavebar {
  0%, 100% { transform: scaleY(0.3); opacity: 0.5; }
  50%      { transform: scaleY(1);    opacity: 1; }
}

/* —— 毛玻璃卡片 —— */
.login-card {
  position: relative;
  width: 408px;
  padding: 44px 44px 30px;
  border-radius: 18px;
  text-align: center;
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.11), rgba(255, 255, 255, 0.04));
  border: 1px solid rgba(255, 255, 255, 0.15);
  -webkit-backdrop-filter: blur(22px) saturate(150%);
          backdrop-filter: blur(22px) saturate(150%);
  box-shadow:
    0 24px 70px rgba(0, 0, 0, 0.45),
    inset 0 1px 0 rgba(255, 255, 255, 0.18);
  animation: cardIn 0.7s cubic-bezier(0.22, 0.8, 0.36, 1) both;
}
.login-card::before {
  content: "";
  position: absolute;
  top: 0; left: 18px; right: 18px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.5), transparent);
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(26px) scale(0.97); }
  to   { opacity: 1; transform: none; }
}

.logo-mark {
  width: 56px; height: 56px;
  margin: 0 auto 14px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #409eff, #00c9b0);
  box-shadow: 0 10px 26px rgba(64, 158, 255, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.badge {
  display: inline-block;
  padding: 3px 14px;
  border-radius: 999px;
  font-size: 12px;
  letter-spacing: 3px;
  color: rgba(255, 255, 255, 0.75);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.14);
}
h2 {
  margin: 14px 0 4px;
  font-size: 27px;
  font-weight: 700;
  letter-spacing: 6px;
  background: linear-gradient(90deg, #ffffff 10%, #bcd6ff 55%, #8fd8ff 100%);
  -webkit-background-clip: text;
          background-clip: text;
  color: transparent;
  filter: drop-shadow(0 2px 18px rgba(64, 158, 255, 0.35));
}
.en {
  margin: 0;
  font-size: 11px;
  letter-spacing: 5px;
  color: rgba(255, 255, 255, 0.45);
}
.divider {
  display: block;
  width: 56px; height: 3px;
  margin: 18px auto 6px;
  border-radius: 3px;
  background: linear-gradient(90deg, #409eff, #00c9b0);
}
.sub {
  margin: 0 0 24px;
  font-size: 13px;
  letter-spacing: 1px;
  color: rgba(255, 255, 255, 0.55);
}

/* —— 玻璃态输入框 —— */
.login-card :deep(.el-form) { text-align: left; }
/* 颜色变量必须声明在 .el-input 自身（组件在自身上声明了 --el-input-bg-color，
   否则会覆盖父级 .el-form-item 上继承下来的值，导致白底） */
.login-card :deep(.el-input) {
  --el-input-bg-color: rgba(255, 255, 255, 0.07);
  --el-input-text-color: #fff;
  --el-input-placeholder-color: rgba(255, 255, 255, 0.4);
  --el-input-icon-color: rgba(255, 255, 255, 0.55);
  --el-input-border-color: transparent;
  --el-input-hover-border-color: transparent;
  --el-input-focus-border-color: transparent;
}
.login-card :deep(.el-form-item) {
  margin-bottom: 20px;
}
.login-card :deep(.el-input__wrapper) {
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.07);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.16) inset;
  transition: box-shadow 0.25s, background 0.25s;
}
.login-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.28) inset;
}
.login-card :deep(.el-input__wrapper.is-focus) {
  background: rgba(255, 255, 255, 0.1);
  box-shadow:
    0 0 0 1.5px #409eff inset,
    0 0 22px rgba(64, 158, 255, 0.4);
}

/* —— 浏览器自动填充（登录页有已存账号时，Chrome 会用 UA 层白底盖住玻璃底，
     必须用同色 inset 阴影抵消 + 锁死文字色，再用长 transition 防填充瞬间白闪） —— */
.login-card :deep(.el-input__inner) {
  transition: background-color 9999s ease-out, -webkit-text-fill-color 9999s ease-out;
}
.login-card :deep(.el-input__inner:-webkit-autofill) {
  -webkit-box-shadow: 0 0 0 1000px rgba(255, 255, 255, 0.07) inset;
  -webkit-text-fill-color: #fff;
  caret-color: #fff;
}

/* —— 渐变登录按钮 —— */
.login-card :deep(.btn) {
  width: 100%;
  height: 48px;
  margin-top: 6px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 10px;
  color: #fff;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #409eff 0%, #00c9b0 100%);
  box-shadow: 0 12px 30px rgba(64, 158, 255, 0.4);
  transition: transform 0.25s, box-shadow 0.25s, filter 0.25s;
}
.login-card :deep(.btn:hover),
.login-card :deep(.btn:focus) {
  color: #fff;
  background: linear-gradient(135deg, #4fa6ff 0%, #12d4bb 100%);
  box-shadow: 0 16px 38px rgba(64, 158, 255, 0.55);
  transform: translateY(-2px);
}
.login-card :deep(.btn.is-loading) {
  filter: brightness(0.96);
}

.page-foot {
  position: absolute;
  bottom: 20px;
  left: 0; right: 0;
  text-align: center;
  font-size: 12px;
  letter-spacing: 1px;
  color: rgba(255, 255, 255, 0.38);
}

@media (max-width: 520px) {
  .login-card { width: 92%; max-width: 408px; padding: 34px 24px 24px; }
  h2 { font-size: 22px; letter-spacing: 4px; }
}
@media (max-height: 640px) {
  .bg-wave { height: 90px; }
}
@media (prefers-reduced-motion: reduce) {
  .bg-orb, .bg-wave span, .login-card { animation: none; }
}
</style>

<template>
  <div class="login-wrap">
    <!-- 背景装饰：网格 + 流动极光画布 + 音波 -->
    <div class="bg-grid" aria-hidden="true"></div>
    <canvas ref="bgCanvas" class="bg-canvas" aria-hidden="true"></canvas>
    <div class="bg-wave" aria-hidden="true">
      <span
        v-for="b in bars"
        :key="b.i"
        :style="{ height: b.h + 'px', animationDuration: b.s + 's', animationDelay: b.d + 's' }"
      ></span>
    </div>

    <div class="login-card">
      <span class="corner corner-tl" aria-hidden="true"></span>
      <span class="corner corner-br" aria-hidden="true"></span>

      <div class="logo-wrap">
        <span class="logo-ring" aria-hidden="true"></span>
        <span class="logo-orbit" aria-hidden="true"><i></i></span>
        <div class="logo-mark">
          <el-icon :size="26" color="#fff"><Microphone /></el-icon>
        </div>
      </div>

      <span class="badge"><i></i>管 理 后 台</span>
      <h2>方言采集平台</h2>
      <p class="en">DIALECT COLLECTION PLATFORM</p>
      <span class="divider"></span>
      <p class="sub">词表导入 · 任务分配 · 审核导出</p>

      <el-form :model="form" :rules="rules" ref="formRef" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <div class="field-row">
            <label class="field-label" for="login-user">账 号</label>
            <el-input id="login-user" v-model="form.username" placeholder="请输入用户名" size="large" :prefix-icon="User" />
          </div>
        </el-form-item>
        <el-form-item prop="password">
          <div class="field-row">
            <label class="field-label" for="login-pass">密 码</label>
            <el-input id="login-pass" v-model="form.password" type="password" placeholder="请输入密码" size="large" show-password :prefix-icon="Lock" />
          </div>
        </el-form-item>
        <el-button type="primary" size="large" class="btn" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>
    </div>

    <p class="page-foot">© 2026 方言采集平台 · 管理后台</p>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted, onBeforeUnmount } from 'vue'
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

// —— 流动极光：全屏 canvas 画 7 团光斑，每团沿“两个不成整倍数的正弦”叠加路径运动，
//    路径永不完全重复 → 背景一直渐渐、无规则地变化 ——
const bgCanvas = ref(null)
let rafId = 0
let removeResize = null

function initAurora() {
  const canvas = bgCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const dpr = Math.min(window.devicePixelRatio || 1, 2)

  // 每团光斑预渲染成离屏径向渐变贴图，逐帧 drawImage 平移（比每帧画渐变省很多）
  const makeSprite = color => {
    const size = 360
    const s = document.createElement('canvas')
    s.width = s.height = size * 2
    const g = s.getContext('2d')
    const gr = g.createRadialGradient(size, size, 0, size, size, size)
    gr.addColorStop(0, `rgba(${color},0.5)`)
    gr.addColorStop(0.4, `rgba(${color},0.24)`)
    gr.addColorStop(1, `rgba(${color},0)`)
    g.fillStyle = gr
    g.fillRect(0, 0, size * 2, size * 2)
    return { img: s, size }
  }

  const colors = ['64,158,255', '0,201,176', '120,110,255', '40,180,255']
  const blobs = Array.from({ length: 7 }, (_, i) => {
    const s = makeSprite(colors[i % colors.length])
    return {
      ...s,
      bx: 0.12 + ((i * 0.31) % 0.76),          // 归一化基位（随视口）
      by: 0.12 + ((i * 0.47 + 0.2) % 0.76),
      ax: 0.10 + ((i * 29) % 40) / 400,          // 摆动幅度
      ay: 0.09 + ((i * 23) % 38) / 420,
      f1: 0.00040 + i * 0.000021,                // 不成整倍数的频率 →
      f2: 0.00017 + i * 0.000037,                // 合成路径不会周期重复
      f3: 0.00031 + i * 0.000029,
      f4: 0.00013 + i * 0.000043,
      p1: i * 1.7, p2: i * 2.3, p3: i * 2.9, p4: i * 1.1,
      q: i * 1.3,
      baseA: 0.30 + (i % 4) * 0.06
    }
  })

  function resize() {
    const w = window.innerWidth
    const h = window.innerHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    canvas.style.width = w + 'px'
    canvas.style.height = h + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()
  window.addEventListener('resize', resize)
  removeResize = () => window.removeEventListener('resize', resize)

  function paint(t) {
    const w = window.innerWidth
    const h = window.innerHeight
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.globalCompositeOperation = 'lighter' // 相加混合 → 光晕叠加出极光
    for (const b of blobs) {
      const x = b.bx * w + b.ax * w * (Math.sin(t * b.f1 + b.p1) + 0.6 * Math.sin(t * b.f2 + b.p2))
      const y = b.by * h + b.ay * h * (Math.sin(t * b.f3 + b.p3) + 0.6 * Math.sin(t * b.f4 + b.p4))
      const pulse = 0.72 + 0.28 * Math.sin(t * 0.00023 + b.q) // 缓慢呼吸
      const sc = 0.9 + 0.14 * Math.sin(t * 0.00031 + b.p1)    // 缓慢缩放
      ctx.globalAlpha = b.baseA * pulse
      ctx.drawImage(b.img, x - b.size * sc, y - b.size * sc, b.size * 2 * sc, b.size * 2 * sc)
    }
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
  }

  function frame(now) {
    paint(now - t0)
    rafId = requestAnimationFrame(frame)
  }
  const t0 = performance.now()
  if (reduce) {
    paint(0) // 减少动态偏好：只画一帧静止极光
  } else {
    rafId = requestAnimationFrame(frame)
  }
}

onMounted(initAurora)
onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  if (removeResize) removeResize()
})

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
  z-index: 1;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
  background-size: 56px 56px;
  -webkit-mask-image: radial-gradient(ellipse at 50% 38%, #000 25%, transparent 78%);
          mask-image: radial-gradient(ellipse at 50% 38%, #000 25%, transparent 78%);
}

/* —— 流动极光画布（光斑路径由 JS 驱动，永不周期重复） —— */
.bg-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none;
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
  z-index: 1;
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
  z-index: 2;
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
    0 0 90px rgba(64, 158, 255, 0.12),
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

/* —— 卡片角落细框线（仪表感） —— */
.corner {
  position: absolute;
  width: 34px; height: 34px;
  pointer-events: none;
}
.corner-tl {
  top: 14px; left: 14px;
  border-top: 1px solid rgba(150, 195, 255, 0.30);
  border-left: 1px solid rgba(150, 195, 255, 0.30);
  border-top-left-radius: 7px;
}
.corner-br {
  bottom: 14px; right: 14px;
  border-bottom: 1px solid rgba(0, 201, 176, 0.30);
  border-right: 1px solid rgba(0, 201, 176, 0.30);
  border-bottom-right-radius: 7px;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(26px) scale(0.97); }
  to   { opacity: 1; transform: none; }
}

/* —— 徽标：渐变块 + 虚点轨道环 + 缓速绕行光点 ——
   logo 用绝对定位 + transform 居中，环用同一容器 inset 定位 → 两者必然同心 */
.logo-wrap {
  position: relative;
  width: 96px; height: 96px;
  margin: 0 auto 12px;
}
.logo-ring {
  position: absolute;
  inset: 6px;
  border: 1px dashed rgba(255, 255, 255, 0.22);
  border-radius: 50%;
}
.logo-orbit {
  position: absolute;
  inset: 6px;
  border-radius: 50%;
  animation: spin 18s linear infinite;
}
.logo-orbit i {
  position: absolute;
  top: -3px;
  left: 50%;
  width: 7px; height: 7px;
  margin-left: -3.5px;
  border-radius: 50%;
  background: #00c9b0;
  box-shadow: 0 0 12px 3px rgba(0, 201, 176, 0.75);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.logo-mark {
  position: absolute;
  top: 50%; left: 50%;
  width: 56px; height: 56px;
  transform: translate(-50%, -50%);
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
.badge i {
  display: inline-block;
  width: 5px; height: 5px;
  margin-right: 7px;
  vertical-align: 1px;
  border-radius: 50%;
  background: linear-gradient(135deg, #409eff, #00c9b0);
  box-shadow: 0 0 8px rgba(0, 201, 176, 0.8);
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
.field-row {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
}
.field-row :deep(.el-input) {
  flex: 1;
}
.field-label {
  flex: none;
  width: 48px;
  text-align: right;
  font-size: 13px;
  letter-spacing: 2px;
  color: rgba(255, 255, 255, 0.65);
}
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
  position: relative;
  overflow: hidden;
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
  box-shadow: 0 12px 30px rgba(64, 158, 255, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.28);
  transition: transform 0.25s, box-shadow 0.25s, filter 0.25s;
}
/* 悬停时一束斜向流光从左侧扫过 */
.login-card :deep(.btn)::after {
  content: "";
  position: absolute;
  top: 0; left: -80%;
  width: 55%;
  height: 100%;
  background: linear-gradient(105deg, transparent, rgba(255, 255, 255, 0.35), transparent);
  transform: skewX(-20deg);
  transition: left 0.6s ease;
}
.login-card :deep(.btn:hover)::after {
  left: 130%;
}
.login-card :deep(.btn:hover),
.login-card :deep(.btn:focus) {
  color: #fff;
  background: linear-gradient(135deg, #4fa6ff 0%, #12d4bb 100%);
  box-shadow: 0 16px 38px rgba(64, 158, 255, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.3);
  transform: translateY(-2px);
}
.login-card :deep(.btn.is-loading) {
  filter: brightness(0.96);
}

.page-foot {
  position: absolute;
  bottom: 20px;
  left: 0; right: 0;
  z-index: 1;
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
  .bg-wave span, .login-card, .logo-orbit { animation: none; }
}
</style>

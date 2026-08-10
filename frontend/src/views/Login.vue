<template>
  <div class="login-wrap">
    <div class="login-card">
      <h2>方言采集平台 · 管理后台</h2>
      <p class="sub">词表导入 · 任务分配 · 审核导出</p>
      <el-form :model="form" :rules="rules" ref="formRef" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" size="large" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password :prefix-icon="Lock" />
        </el-form-item>
        <el-button type="primary" size="large" class="btn" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
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
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1d2b3a 0%, #2c4a6e 100%);
}
.login-card {
  width: 380px;
  background: #fff;
  border-radius: 10px;
  padding: 40px 36px 32px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
h2 {
  margin: 0 0 6px;
  font-size: 20px;
  text-align: center;
}
.sub {
  margin: 0 0 28px;
  text-align: center;
  color: #999;
  font-size: 13px;
}
.btn {
  width: 100%;
}
</style>

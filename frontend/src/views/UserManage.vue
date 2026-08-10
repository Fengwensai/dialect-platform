<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header">
          <b>管理员账号</b>
          <el-button type="primary" :icon="Plus" @click="openCreate">新增管理员</el-button>
        </div>
      </template>

      <el-table :data="users" v-loading="loading" border>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" width="160" />
        <el-table-column prop="name" label="姓名" width="140" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag :type="row.role === 'super_admin' ? 'danger' : 'primary'" size="small">
              {{ row.role === 'super_admin' ? '超级管理员' : '省管理员' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="管辖省份" width="140">
          <template #default="{ row }">{{ row.province_code ? regionName(row.province_code) : '全国' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="160">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" :disabled="row.id === auth.admin?.id" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑管理员' : '新增管理员'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="!!editingId" placeholder="登录账号" />
        </el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="密码" :required="!editingId">
          <el-input v-model="form.password" type="password" show-password :placeholder="editingId ? '留空则不修改' : '至少 6 位'" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio value="super_admin">超级管理员</el-radio>
            <el-radio value="province_admin">省管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.role === 'province_admin'" label="管辖省份">
          <el-select v-model="form.province_code" placeholder="选择省份" style="width: 100%">
            <el-option v-for="p in regionStore.tree" :key="p.code" :label="p.name" :value="p.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'
import { useRegionStore } from '../stores/regions'

const auth = useAuthStore()
const regionStore = useRegionStore()
const loading = ref(false)
const saving = ref(false)
const users = ref([])
const dialogVisible = ref(false)
const editingId = ref(null)
const form = reactive({ username: '', name: '', password: '', role: 'province_admin', province_code: '' })

function regionName(code) {
  return regionStore.nameOf(code)
}

async function load() {
  loading.value = true
  try {
    users.value = await request.get('/users')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { username: '', name: '', password: '', role: 'province_admin', province_code: '' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { username: row.username, name: row.name, password: '', role: row.role, province_code: row.province_code || '' })
  dialogVisible.value = true
}

async function save() {
  if (!editingId.value && !form.username) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (!editingId.value && form.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  saving.value = true
  try {
    const body = { name: form.name, role: form.role, province_code: form.province_code || null }
    if (!editingId.value) {
      body.username = form.username
      body.password = form.password
      await request.post('/users', body)
    } else {
      if (form.password) body.password = form.password
      await request.patch(`/users/${editingId.value}`, body)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除管理员「${row.username}」吗？`, '提示', { type: 'warning' })
  await request.delete(`/users/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  await regionStore.ensureLoaded()
  load()
})
</script>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>

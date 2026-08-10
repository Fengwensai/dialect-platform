<template>
  <div>
    <!-- 工具栏 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="filter-bar">
        <span class="hint">团队码一码一区（省+市）：发音人凭码绑定属地，绑定后只能看到/录制该地区任务</span>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建团队码</el-button>
        <span class="total">共 {{ items.length }} 个</span>
      </div>
    </el-card>

    <!-- 团队码表格 -->
    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="code" label="团队码" width="140">
          <template #default="{ row }">
            <el-tag type="primary" effect="plain">{{ row.code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="团队名" min-width="140" show-overflow-tooltip />
        <el-table-column label="省" width="110">
          <template #default="{ row }">{{ regionName(row.province_code) }}</template>
        </el-table-column>
        <el-table-column label="市" width="120">
          <template #default="{ row }">{{ regionName(row.city_code) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">改名</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建对话框 -->
    <el-dialog v-model="createVisible" title="新建团队码" width="460px">
      <el-form :model="createForm" label-width="90px">
        <el-form-item label="团队码">
          <el-input v-model="createForm.code" placeholder="如 SY-2101 / HB-SJZ，建议见码知地区" />
        </el-form-item>
        <el-form-item label="团队名">
          <el-input v-model="createForm.name" placeholder="如 沈阳团队" />
        </el-form-item>
        <el-form-item label="省">
          <el-select
            v-model="createForm.province_code"
            placeholder="选择省份"
            filterable
            :disabled="!auth.isSuper"
            style="width: 100%"
            @change="createForm.city_code = ''"
          >
            <el-option v-for="p in provinceOptions" :key="p.code" :label="p.name" :value="p.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="市">
          <el-select
            v-model="createForm.city_code"
            placeholder="选择城市"
            filterable
            style="width: 100%"
          >
            <el-option v-for="c in createCityOptions" :key="c.code" :label="c.name" :value="c.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <!-- 改名对话框 -->
    <el-dialog v-model="editVisible" title="团队码改名" width="420px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="团队名">
          <el-input v-model="editForm.name" placeholder="请输入新的团队名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'
import { useRegionStore } from '../stores/regions'

const auth = useAuthStore()
const regionStore = useRegionStore()

const loading = ref(false)
const saving = ref(false)
const items = ref([])

const createVisible = ref(false)
const createForm = reactive({ code: '', name: '', province_code: '', city_code: '' })

const editVisible = ref(false)
const editForm = reactive({ id: null, name: '' })

const provinceOptions = computed(() => {
  if (auth.isSuper) return regionStore.tree
  const locked = auth.provinceCode
  return locked ? (regionStore.tree || []).filter((p) => p.code === locked) : []
})

const createCityOptions = computed(() => {
  const p = (regionStore.tree || []).find((x) => x.code === createForm.province_code)
  return (p && p.children) || []
})

function regionName(code) {
  return regionStore.nameOf(code)
}

async function load() {
  loading.value = true
  try {
    const data = await request.get('/team-codes')
    items.value = data || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createForm, { code: '', name: '', province_code: auth.provinceCode || '', city_code: '' })
  createVisible.value = true
}

async function create() {
  if (!createForm.code.trim()) {
    ElMessage.warning('请填写团队码')
    return
  }
  if (!createForm.province_code || !createForm.city_code) {
    ElMessage.warning('请选择省和市')
    return
  }
  saving.value = true
  try {
    await request.post('/team-codes', {
      code: createForm.code.trim(),
      name: createForm.name.trim(),
      province_code: createForm.province_code,
      city_code: createForm.city_code
    })
    ElMessage.success('已创建（一码一区）')
    createVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

function openEdit(row) {
  Object.assign(editForm, { id: row.id, name: row.name || '' })
  editVisible.value = true
}

async function save() {
  if (!editForm.name.trim()) {
    ElMessage.warning('团队名不能为空')
    return
  }
  saving.value = true
  try {
    await request.patch(`/team-codes/${editForm.id}`, { name: editForm.name.trim() })
    ElMessage.success('已保存')
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

function remove(row) {
  ElMessageBox.confirm(
    `删除团队码「${row.code}」（${regionName(row.province_code)}·${regionName(row.city_code)}）？已绑定的发音人不受影响，但该码不能再用于新绑定。`,
    '确认删除',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
    .then(async () => {
      await request.delete(`/team-codes/${row.id}`)
      ElMessage.success('已删除')
      load()
    })
    .catch(() => {})
}

onMounted(async () => {
  await regionStore.ensureLoaded()
  load()
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hint {
  color: #909399;
  font-size: 13px;
  flex: 1;
  min-width: 240px;
}
.total {
  color: #909399;
  font-size: 13px;
}
</style>

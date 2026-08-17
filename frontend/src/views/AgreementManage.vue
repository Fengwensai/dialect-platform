<template>
  <div>
    <!-- 工具栏 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="filter-bar">
        <span class="hint">三类协议由管理员维护：编辑即生成新版本（旧版本不可变），保存后所有发音人需重新同意方可继续使用小程序</span>
      </div>
    </el-card>

    <!-- 协议表格 -->
    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" border stripe>
        <el-table-column label="类型" width="160">
          <template #default="{ row }">
            <el-tag type="info" effect="plain">{{ typeName(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最新版本" width="100">
          <template #default="{ row }">
            <el-tag type="primary" effect="plain">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ row.updated_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="info" @click="openHistory(row)">历史</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 编辑（生成新版本）对话框 -->
    <el-dialog v-model="editVisible" :title="`编辑${typeName(editForm.type)}`" width="640px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="类型">
          <el-input :value="typeName(editForm.type)" disabled />
        </el-form-item>
        <el-form-item label="新版本号">
          <el-input :value="`v${(editBaseVersion || 0) + 1}`" disabled />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="editForm.title" placeholder="协议标题" />
        </el-form-item>
        <el-form-item label="正文内容">
          <el-input v-model="editForm.content" type="textarea" :rows="14" placeholder="请输入协议全文" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存为新版本</el-button>
      </template>
    </el-dialog>

    <!-- 历史版本对话框 -->
    <el-dialog v-model="historyVisible" :title="`${typeName(historyType)}·历史版本`" width="680px">
      <el-table :data="historyItems" v-loading="historyLoading" border stripe>
        <el-table-column label="版本" width="90">
          <template #default="{ row }">
            <el-tag :type="row.version === maxVersion ? 'primary' : 'info'" effect="plain">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ row.updated_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewContent(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 历史版本内容对话框 -->
    <el-dialog v-model="contentVisible" :title="`${typeName(historyType)} v${currentVersion}`" width="680px">
      <pre class="content-pre">{{ currentContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api/request'

const TYPE_NAMES = {
  user_agreement: '用户协议',
  privacy_policy: '隐私政策',
  voice_auth: '声音单独授权协议'
}

function typeName(type) {
  return TYPE_NAMES[type] || type
}

const loading = ref(false)
const saving = ref(false)
const items = ref([])

const editVisible = ref(false)
const editForm = reactive({ type: '', title: '', content: '' })
const editBaseVersion = ref(0)

const historyVisible = ref(false)
const historyLoading = ref(false)
const historyItems = ref([])
const historyType = ref('')

const contentVisible = ref(false)
const currentContent = ref('')
const currentVersion = ref('')

const maxVersion = computed(() =>
  historyItems.value.length ? Math.max(...historyItems.value.map((h) => h.version)) : 0
)

async function load() {
  loading.value = true
  try {
    const data = await request.get('/agreements')
    items.value = data || []
  } finally {
    loading.value = false
  }
}

function openEdit(row) {
  Object.assign(editForm, { type: row.type, title: row.title, content: row.content })
  editBaseVersion.value = row.version
  editVisible.value = true
}

async function save() {
  if (!editForm.title.trim()) {
    ElMessage.warning('协议标题不能为空')
    return
  }
  if (!editForm.content.trim()) {
    ElMessage.warning('协议正文内容不能为空')
    return
  }
  const nextVersion = editBaseVersion.value + 1
  try {
    await ElMessageBox.confirm(
      `保存后将生成 ${typeName(editForm.type)} 的 v${nextVersion}，所有发音人下次登录需重新阅读并同意该协议。确定保存？`,
      '确认发布新版本',
      { type: 'warning', confirmButtonText: '保存', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  saving.value = true
  try {
    await request.post('/agreements', {
      type: editForm.type,
      title: editForm.title.trim(),
      content: editForm.content.trim()
    })
    ElMessage.success(`已保存为新版本 v${nextVersion}`)
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function openHistory(row) {
  historyType.value = row.type
  historyVisible.value = true
  historyLoading.value = true
  try {
    const data = await request.get('/agreements/history', { params: { type: row.type } })
    historyItems.value = data || []
  } finally {
    historyLoading.value = false
  }
}

function viewContent(row) {
  currentVersion.value = row.version
  currentContent.value = row.content
  contentVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  flex: 1;
  min-width: 240px;
}
.content-pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-primary);
  max-height: 60vh;
  overflow: auto;
  margin: 0;
}
</style>

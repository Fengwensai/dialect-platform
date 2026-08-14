<template>
  <div>
    <!-- 筛选栏 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="filter-bar">
        <el-select
          v-model="filterTaskId"
          placeholder="全部任务"
          clearable
          filterable
          style="width: 260px"
        >
          <el-option v-for="t in taskOptions" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 150px">
          <el-option label="待审核" value="pending" />
          <el-option label="已通过" value="approved" />
          <el-option label="已驳回" value="rejected" />
        </el-select>
        <el-input
          v-model="filterKeyword"
          placeholder="搜索发音人/词条"
          clearable
          style="width: 200px"
          @keyup.enter="page = 1; load()"
        />
        <el-select v-model="filterProvince" placeholder="全部省份" clearable filterable style="width: 140px">
          <el-option v-for="p in provinceOptions" :key="p.code" :label="p.name" :value="p.code" />
        </el-select>
        <el-select v-model="sortBy" style="width: 130px">
          <el-option label="待审优先" value="pending_first" />
          <el-option label="按提交时间" value="created" />
          <el-option label="按音频时长" value="duration" />
          <el-option label="按审核时间" value="reviewed" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="load">查询</el-button>
        <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        <el-button
          type="success"
          :icon="Download"
          :loading="exporting"
          @click="exportDataset"
        >
          导出已通过数据集
        </el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>
    </el-card>

    <!-- 录音表格 -->
    <el-card shadow="never">
      <!-- 批量审核操作条 -->
      <div v-if="selection.length" class="batch-bar">
        <span class="batch-tip">
          已选 <b class="sel-count">{{ selection.length }}</b> 条待审核录音
        </span>
        <el-button type="success" size="small" :icon="CircleCheck" :loading="batchLoading" @click="batchApprove">
          批量通过
        </el-button>
        <el-button type="danger" size="small" :icon="CircleClose" :loading="batchLoading" @click="batchReject">
          批量驳回
        </el-button>
        <el-button size="small" @click="clearSelection">取消选择</el-button>
      </div>
      <el-table
        :data="items"
        v-loading="loading"
        border
        stripe
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="45" :selectable="(row) => row.status === 'pending'" />
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="task_name" label="任务" min-width="130" show-overflow-tooltip />
        <el-table-column label="词条" min-width="150">
          <template #default="{ row }">
            <span class="word">{{ row.word_content }}</span>
            <span v-if="row.word_code" class="code">{{ row.word_code }}</span>
          </template>
        </el-table-column>
        <el-table-column label="发音人" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.speaker_nickname || row.speaker_device || '-' }}</template>
        </el-table-column>
        <el-table-column label="音频" min-width="250">
          <template #default="{ row }">
            <audio controls :src="row.audio_url" preload="none" class="player" />
          </template>
        </el-table-column>
        <el-table-column label="转写" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <div v-if="row.mandarin_transcript || row.dialect_transcript" class="tr-box">
              <div v-if="row.mandarin_transcript" class="tr-item">
                <span class="tr-label">普</span>{{ row.mandarin_transcript }}
              </div>
              <div v-if="row.dialect_transcript" class="tr-item">
                <span class="tr-label">方</span>{{ row.dialect_transcript }}
              </div>
            </div>
            <span v-else class="tr-empty">-</span>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="80">
          <template #default="{ row }">{{ fmtDuration(row.audio_duration) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type || 'info'" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="review_note" label="审核备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.review_note || '-' }}</template>
        </el-table-column>
        <el-table-column prop="reviewed_by_name" label="审核人" width="90">
          <template #default="{ row }">{{ row.reviewed_by_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="提交时间" width="150">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openTrans(row)">转写</el-button>
            <el-button v-if="row.status !== 'approved'" link type="success" @click="approve(row)">通过</el-button>
            <el-button v-if="row.status !== 'rejected'" link type="danger" @click="reject(row)">驳回</el-button>
            <template v-if="row.status === 'rejected'">
              <el-button link type="warning" :icon="RefreshLeft" @click="resetReview(row)">重置</el-button>
              <el-button link type="danger" :icon="Delete" @click="removeRecording(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <!-- 转写编辑弹窗 -->
      <el-dialog v-model="transDialog.visible" title="录音转写" width="520px" :close-on-click-modal="false">
        <el-form label-width="96px">
          <el-form-item label="词条">
            <b>{{ transDialog.word }}</b>
          </el-form-item>
          <el-form-item label="普通话转写">
            <el-input
              v-model="transDialog.mandarin"
              type="textarea"
              :rows="2"
              placeholder="听录音，用普通话转写读音/词义"
              maxlength="1000"
              show-word-limit
            />
          </el-form-item>
          <el-form-item label="方言转写">
            <el-input
              v-model="transDialog.dialect"
              type="textarea"
              :rows="2"
              placeholder="方言拼音 / 国际音标等（可空）"
              maxlength="1000"
              show-word-limit
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="transDialog.visible = false">取消</el-button>
          <el-button type="primary" :loading="savingTrans" @click="saveTrans">保存</el-button>
        </template>
      </el-dialog>

      <el-pagination
        class="pager"
        background
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="(p) => { page = p; load() }"
        @size-change="(s) => { pageSize = s; page = 1; load() }"
      />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, RefreshLeft, Download, CircleCheck, CircleClose, Delete } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'
import { useRegionStore } from '../stores/regions'

const auth = useAuthStore()
const regionStore = useRegionStore()

const statusMeta = {
  pending: { type: 'warning', label: '待审核' },
  approved: { type: 'success', label: '已通过' },
  rejected: { type: 'danger', label: '已驳回' }
}

const loading = ref(false)
const exporting = ref(false)
const batchLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterTaskId = ref(null)
const filterStatus = ref('pending')
const filterKeyword = ref('')
const filterProvince = ref('')
const sortBy = ref('pending_first')
const selection = ref([])
const taskOptions = ref([])
const transDialog = ref({ visible: false, id: null, word: '', mandarin: '', dialect: '' })
const savingTrans = ref(false)

const provinceOptions = computed(() => {
  if (auth.isSuper) return regionStore.tree
  const locked = auth.provinceCode
  return locked ? (regionStore.tree || []).filter((p) => p.code === locked) : []
})

function onSelectionChange(rows) {
  selection.value = rows
}
function clearSelection() {
  selection.value = []
}

function fmtDuration(ms) {
  if (!ms) return '-'
  const s = ms / 1000
  return s.toFixed(1) + 's'
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filterTaskId.value) params.task_id = filterTaskId.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterKeyword.value) params.keyword = filterKeyword.value
    if (filterProvince.value) params.province_code = filterProvince.value
    if (sortBy.value) params.sort_by = sortBy.value
    const data = await request.get('/review/recordings', { params })
    items.value = data.items
    total.value = data.total
    selection.value = [] // 翻页/刷新后清空勾选，避免残留
  } finally {
    loading.value = false
  }
}

function reset() {
  filterTaskId.value = null
  filterStatus.value = 'pending'
  filterKeyword.value = ''
  filterProvince.value = ''
  sortBy.value = 'pending_first'
  page.value = 1
  load()
}

function refresh() {
  // 当前页审空则回退一页，避免停留在空页
  if (items.value.length === 1 && page.value > 1) page.value--
  load()
}

async function exportDataset() {
  // 始终导出 approved；只尊重任务筛选，忽略状态下拉（按钮名已指明“已通过”）。
  // 用原生 fetch：axios 拦截器会剥掉 headers（拿不到 Content-Disposition 文件名），
  // 且错误响应在 blob 模式下 detail 读不到。
  const params = new URLSearchParams()
  if (filterTaskId.value) params.set('task_id', filterTaskId.value)
  const qs = params.toString()
  const token = localStorage.getItem('token') || ''
  exporting.value = true
  try {
    const resp = await fetch(qs ? `/api/review/export?${qs}` : '/api/review/export', {
      headers: { Authorization: `Bearer ${token}` }
    })
    if (!resp.ok) {
      let msg = '导出失败'
      try {
        const data = await resp.json()
        if (data?.detail) msg = data.detail
      } catch (e) { /* 非 JSON 错误体，用默认提示 */ }
      ElMessage.error(msg)
      return
    }
    const blob = await resp.blob()
    let filename = `dialect_dataset_${Date.now()}.zip`
    const cd = resp.headers.get('Content-Disposition') || ''
    const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i)
    if (m && m[1]) filename = decodeURIComponent(m[1])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('数据集已导出')
  } finally {
    exporting.value = false
  }
}

function openTrans(row) {
  transDialog.value = {
    visible: true,
    id: row.id,
    word: row.word_content || '',
    mandarin: row.mandarin_transcript || '',
    dialect: row.dialect_transcript || ''
  }
}

async function saveTrans() {
  savingTrans.value = true
  try {
    await request.patch(`/review/recordings/${transDialog.value.id}/transcript`, {
      mandarin_transcript: transDialog.value.mandarin || null,
      dialect_transcript: transDialog.value.dialect || null
    })
    ElMessage.success('转写已保存')
    transDialog.value.visible = false
    refresh()
  } finally {
    savingTrans.value = false
  }
}

async function approve(row) {
  await ElMessageBox.confirm(`确定通过录音 #${row.id}「${row.word_content}」吗？`, '通过', { type: 'success' })
  await request.post(`/review/recordings/${row.id}/verdict`, { approved: true })
  ElMessage.success('已通过')
  refresh()
}

async function reject(row) {
  let value
  try {
    const res = await ElMessageBox.prompt(`驳回录音 #${row.id}「${row.word_content}」`, '驳回', {
      inputPlaceholder: '驳回原因（可选），如：口音不标准 / 背景噪音大',
      inputValue: ''
    })
    value = res.value
  } catch (e) {
    return // 取消
  }
  await request.post(`/review/recordings/${row.id}/verdict`, { approved: false, note: value || null })
  ElMessage.success('已驳回')
  refresh()
}

async function batchApprove() {
  const n = selection.value.length
  await ElMessageBox.confirm(`确定批量通过选中的 ${n} 条录音吗？`, '批量通过', { type: 'success' })
  await doBatch(true, null)
}

async function batchReject() {
  let value
  try {
    const res = await ElMessageBox.prompt('批量驳回选中的待审核录音', '批量驳回', {
      inputPlaceholder: '统一驳回原因（可选），如：口音不标准 / 背景噪音大',
      inputValue: ''
    })
    value = res.value
  } catch (e) {
    return // 取消
  }
  await doBatch(false, value || null)
}

async function doBatch(approved, note) {
  batchLoading.value = true
  try {
    const ids = selection.value.map((r) => r.id)
    const data = await request.post('/review/batch-verdict', { recording_ids: ids, approved, note })
    ElMessage.success(`已处理 ${data.processed} 条${data.skipped ? `，跳过已审 ${data.skipped} 条` : ''}`)
    selection.value = []
    refresh()
  } finally {
    batchLoading.value = false
  }
}

async function resetReview(row) {
  await ElMessageBox.confirm(`确定将录音 #${row.id}「${row.word_content}」重置回待审吗？`, '重置为待审', { type: 'warning' })
  await request.post(`/review/recordings/${row.id}/reset`)
  ElMessage.success('已重置为待审')
  refresh()
}

async function removeRecording(row) {
  await ElMessageBox.confirm(`确定删除录音 #${row.id}「${row.word_content}」吗？删除后发音人可重新录制。`, '删除录音', { type: 'error' })
  await request.delete(`/review/recordings/${row.id}`)
  ElMessage.success('已删除')
  refresh()
}

onMounted(async () => {
  // 省份下拉 + 任务下拉选项（复用行政区划树与后台任务列表接口）
  await regionStore.ensureLoaded()
  try {
    const data = await request.get('/tasks', { params: { page_size: 200 } })
    taskOptions.value = data.items
  } catch (e) {
    taskOptions.value = []
  }
  load()
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.total {
  color: #909399;
  font-size: 13px;
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 6px;
}
.batch-tip {
  font-size: 13px;
  color: #606266;
}
.sel-count {
  color: #e6a23c;
  font-weight: 600;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.word {
  font-weight: 600;
  color: #303133;
}
.code {
  margin-left: 6px;
  color: #909399;
  font-size: 12px;
}
.player {
  width: 240px;
  height: 36px;
  vertical-align: middle;
}
.tr-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tr-item {
  font-size: 13px;
  color: #303133;
}
.tr-label {
  display: inline-block;
  width: 18px;
  margin-right: 6px;
  padding: 0 2px;
  border-radius: 3px;
  background: #ecf5ff;
  color: #409eff;
  font-size: 12px;
  text-align: center;
}
.tr-empty {
  color: #c0c4cc;
}
</style>

<template>
  <div>
    <!-- 筛选栏 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="filter-bar">
        <el-cascader
          v-model="filterRegion"
          :options="regionStore.tree"
          :props="{ value: 'code', label: 'name', children: 'children', checkStrictly: true, emitPath: true }"
          placeholder="省 / 市 / 区"
          clearable
          filterable
          style="width: 300px"
        />
        <el-input v-model="keyword" placeholder="搜索词条 / 方言点 / 编号" clearable style="width: 240px" @keyup.enter="load" />
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 120px" @change="load">
          <el-option label="启用" value="active" />
          <el-option label="禁用" value="disabled" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="load">查询</el-button>
        <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        <el-button type="success" :icon="Download" :loading="exporting" @click="exportWords">导出清单</el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>
    </el-card>

    <!-- 词条表格（el-table-v2 虚拟渲染，支持大列表流畅滚动） -->
    <el-card shadow="never">
      <!-- 批量操作条（手动 checkbox 列勾选） -->
      <div v-if="selection.length" class="batch-bar">
        <span class="batch-tip">已选 <b class="sel-count">{{ selection.length }}</b> 条词条</span>
        <el-button type="success" size="small" :loading="batchLoading" @click="batchStatus('active')">批量启用</el-button>
        <el-button type="warning" size="small" :loading="batchLoading" @click="batchStatus('disabled')">批量禁用</el-button>
        <el-button type="danger" size="small" :loading="batchLoading" @click="batchDelete">批量删除</el-button>
        <el-button size="small" :disabled="batchLoading" @click="clearSelection">取消选择</el-button>
      </div>
      <!-- el-auto-resizer 提供数值型 width/height，随容器自适应（table-v2 的 width 必须为数字） -->
      <div style="height: calc(100vh - 300px)">
        <el-auto-resizer>
          <template #default="{ height, width }">
            <el-table-v2
              v-loading="loading"
              :columns="columns"
              :data="items"
              :width="width"
              :height="height"
              row-key="id"
              border
              stripe
            />
          </template>
        </el-auto-resizer>
      </div>

      <el-pagination
        class="pager"
        background
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        :page-sizes="[20, 50, 100, 200, 500]"
        @current-change="(p) => { page = p; load() }"
        @size-change="(s) => { pageSize = s; page = 1; load() }"
      />
    </el-card>

    <!-- 编辑对话框 -->
    <el-dialog v-model="editVisible" title="编辑词条" width="560px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="编号"><el-input v-model="editForm.code" /></el-form-item>
        <el-form-item label="方言点">
          <el-input v-model="editForm.dialect_point" @input="onDialectPointInput" placeholder="如：石家庄市长安区" />
        </el-form-item>
        <el-form-item label="词条内容"><el-input v-model="editForm.content" /></el-form-item>
        <el-form-item label="例句"><el-input v-model="editForm.example_sentence" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="发音提示"><el-input v-model="editForm.pronunciation_hint" placeholder="同音字/拼音，帮助发音人" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="editForm.remark" /></el-form-item>
        <el-form-item label="行政区划">
          <el-cascader
            v-model="editRegion"
            :options="regionStore.tree"
            :props="{ value: 'code', label: 'name', children: 'children', checkStrictly: true, emitPath: true }"
            placeholder="留空则由系统按方言点自动匹配"
            clearable
            filterable
            style="width: 100%"
            @change="editRegionTouched = true"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 合并对话框 -->
    <el-dialog v-model="mergeVisible" title="合并词条" width="540px">
      <p class="merge-tip">
        将把词条 <b>「{{ mergeRow?.content }}」</b>（#{{ mergeRow?.id }}）合并到下方选中的目标词条：
        其录音 / 领取 / 任务引用将转入目标，当前词条被删除。合并不可撤销。
      </p>
      <el-form label-width="70px">
        <el-form-item label="目标词条">
          <el-select
            v-model="mergeTarget"
            placeholder="输入编号 / 词条 / 方言点搜索"
            filterable
            remote
            clearable
            :remote-method="searchMergeWords"
            :loading="mergeLoading"
            style="width: 100%"
          >
            <el-option
              v-for="w in mergeOptions"
              :key="w.id"
              :value="w.id"
              :disabled="w.id === mergeRow?.id"
              :label="`#${w.id} ${w.content}${w.code ? '（' + w.code + '）' : ''}${w.dialect_point ? ' @' + w.dialect_point : ''}`"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mergeVisible = false">取消</el-button>
        <el-button type="danger" :loading="merging" :disabled="!mergeTarget" @click="doMerge">合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, h, onMounted, reactive, ref } from 'vue'
import { ElButton, ElCheckbox, ElMessage, ElMessageBox, ElSwitch, ElTag } from 'element-plus'
import { Download, RefreshLeft, Search } from '@element-plus/icons-vue'
import request from '../api/request'
import { useRegionStore } from '../stores/regions'
import { downloadFile } from '../utils/download'

const regionStore = useRegionStore()
const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const filterRegion = ref([])
const filterStatus = ref('')

const editVisible = ref(false)
const editForm = reactive({ id: null, code: '', dialect_point: '', content: '', example_sentence: '', pronunciation_hint: '', remark: '' })
const editRegion = ref([])
const editRegionTouched = ref(false)

const mergeVisible = ref(false)
const mergeRow = ref(null)
const mergeOptions = ref([])
const mergeTarget = ref(null)
const mergeLoading = ref(false)
const merging = ref(false)

// —— 批量操作（el-table-v2 无内置多选，用手动 checkbox 列）——
const selection = ref([])
const batchLoading = ref(false)
const selectedIds = computed(() => new Set(selection.value))
const allChecked = computed(
  () => items.value.length > 0 && selection.value.length === items.value.length
)
const someChecked = computed(
  () => selection.value.length > 0 && selection.value.length < items.value.length
)

function toggleRow(row, checked) {
  const s = new Set(selection.value)
  if (checked) s.add(row.id)
  else s.delete(row.id)
  selection.value = [...s]
}

function toggleAll(checked) {
  selection.value = checked ? items.value.map((w) => w.id) : []
}

function clearSelection() {
  selection.value = []
}

function regionName(code) {
  return regionStore.nameOf(code)
}

// el-table-v2 列配置（cellRenderer 返回 VNode，渲染自定义单元格）
// 注意：cellRenderer 收到的 props 是 { rowData, rowIndex, ... }（无 row），
// 自定义单元格一律从 rowData 取字段。
const columns = computed(() => [
  {
    key: 'selection',
    title: '',
    width: 45,
    align: 'center',
    cellRenderer: ({ rowData }) =>
      h(ElCheckbox, {
        modelValue: selectedIds.value.has(rowData.id),
        onChange: (val) => toggleRow(rowData, val)
      }),
    headerCellRenderer: () =>
      h(ElCheckbox, {
        modelValue: allChecked.value,
        indeterminate: someChecked.value,
        onChange: (val) => toggleAll(val)
      })
  },
  { key: 'id', dataKey: 'id', title: 'ID', width: 60 },
  { key: 'code', dataKey: 'code', title: '编号', width: 100, showOverflowTooltip: true },
  { key: 'dialect_point', dataKey: 'dialect_point', title: '方言点', width: 150, showOverflowTooltip: true },
  { key: 'content', dataKey: 'content', title: '词条内容', width: 160, showOverflowTooltip: true },
  { key: 'example_sentence', dataKey: 'example_sentence', title: '例句', width: 180, showOverflowTooltip: true },
  { key: 'pronunciation_hint', dataKey: 'pronunciation_hint', title: '发音提示', width: 110, showOverflowTooltip: true },
  {
    key: 'region',
    title: '行政区划',
    width: 200,
    cellRenderer: ({ rowData }) => {
      if (!rowData.province_code) return h(ElTag, { type: 'warning', size: 'small' }, () => '未匹配')
      const parts = [regionName(rowData.province_code)]
      if (rowData.city_code) parts.push(regionName(rowData.city_code))
      if (rowData.district_code) parts.push(regionName(rowData.district_code))
      return parts.join('-')
    }
  },
  {
    key: 'status',
    title: '状态',
    width: 96,
    cellRenderer: ({ rowData }) =>
      h(ElSwitch, {
        modelValue: rowData.status === 'active',
        activeText: '启用',
        inactiveText: '禁用',
        inlinePrompt: true,
        onChange: (val) => toggleStatus(rowData, val)
      })
  },
  {
    key: 'created_at',
    title: '导入时间',
    width: 150,
    cellRenderer: ({ rowData }) => rowData.created_at?.slice(0, 16) || '-'
  },
  {
    key: 'actions',
    title: '操作',
    width: 280,
    fixed: 'right',
    cellRenderer: ({ rowData }) =>
      h('div', { class: 'actions-cell' }, [
        h(ElButton, { link: true, type: 'primary', onClick: () => exportWordRecordings(rowData) }, () => '下载录音'),
        h(ElButton, { link: true, type: 'primary', onClick: () => openEdit(rowData) }, () => '编辑'),
        h(ElButton, { link: true, type: 'warning', onClick: () => openMerge(rowData) }, () => '合并'),
        h(ElButton, { link: true, type: 'danger', onClick: () => remove(rowData) }, () => '删除')
      ])
  }
])

function regionParams() {
  const [p, c, d] = filterRegion.value || []
  const params = {}
  if (p) params.province_code = p
  if (c) params.city_code = c
  if (d) params.district_code = d
  return params
}

async function load() {
  loading.value = true
  try {
    const data = await request.get('/words', {
      params: { page: page.value, page_size: pageSize.value, keyword: keyword.value, status: filterStatus.value || undefined, ...regionParams() }
    })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
  selection.value = [] // 翻页/刷新后清空勾选（仅当前页多选）
}

function reset() {
  keyword.value = ''
  filterRegion.value = []
  filterStatus.value = ''
  page.value = 1
  load()
}

/** 导出当前筛选下的词条清单 CSV（含采集难度/通过率/驳回率） */
async function exportWords() {
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  const [p, c, d] = filterRegion.value || []
  if (p) params.set('province_code', p)
  if (c) params.set('city_code', c)
  if (d) params.set('district_code', d)
  const qs = params.toString()
  await downloadFile(
    qs ? `/api/words/export?${qs}` : '/api/words/export',
    `words_manifest_${Date.now()}.csv`,
    exporting
  )
}

/** 下载某词条全部录音 ZIP（含驳回/待审） */
async function exportWordRecordings(row) {
  await downloadFile(
    `/api/words/${row.id}/recordings/export`,
    `word_${row.id}_recordings_${Date.now()}.zip`,
    null // 行内操作不显 spinner
  )
}

/** 启用/禁用词条开关 */
async function toggleStatus(row, enabled) {
  const status = enabled ? 'active' : 'disabled'
  try {
    await request.patch(`/words/${row.id}`, { status })
    ElMessage.success(enabled ? '已启用' : '已禁用')
    load()
  } catch (e) {
    load() // 失败时恢复开关显示
  }
}

function openEdit(row) {
  Object.assign(editForm, {
    id: row.id, code: row.code || '', dialect_point: row.dialect_point || '',
    content: row.content, example_sentence: row.example_sentence || '',
    pronunciation_hint: row.pronunciation_hint || '', remark: row.remark || ''
  })
  editRegion.value = regionStore.cascaderValue(row.province_code, row.city_code, row.district_code)
  editRegionTouched.value = false
  editVisible.value = true
}

function onDialectPointInput() {
  // 改了方言点后清空手选区划，交给后端自动匹配
  editRegion.value = []
  editRegionTouched.value = false
}

async function save() {
  const content = editForm.content.trim()
  // 查重提示（仅提示不拦截：方言词同词异音可能合法，用户确认后可继续保存）
  if (content) {
    const dup = await request.get('/words/check-duplicate', { params: { content, exclude_word_id: editForm.id } })
    if (dup.duplicate) {
      const hit = dup.word
      const tip = `已存在相同内容词条 #${hit.id}「${hit.content}」${hit.dialect_point ? '（' + hit.dialect_point + '）' : ''}，仍要保存吗？`
      try {
        await ElMessageBox.confirm(tip, '查重提示', { type: 'warning', confirmButtonText: '仍要保存', cancelButtonText: '取消' })
      } catch (e) {
        return // 用户取消
      }
    }
  }

  saving.value = true
  try {
    const body = {
      code: editForm.code,
      dialect_point: editForm.dialect_point,
      content,
      example_sentence: editForm.example_sentence,
      pronunciation_hint: editForm.pronunciation_hint,
      remark: editForm.remark
    }
    if (editRegionTouched.value) {
      const [p, c, d] = editRegion.value || []
      body.province_code = p || null
      body.city_code = c || null
      body.district_code = d || null
    }
    await request.patch(`/words/${editForm.id}`, body)
    ElMessage.success('已保存')
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

function openMerge(row) {
  mergeRow.value = row
  mergeTarget.value = null
  mergeOptions.value = []
  mergeVisible.value = true
}

async function searchMergeWords(query) {
  if (!query) {
    mergeOptions.value = []
    return
  }
  mergeLoading.value = true
  try {
    const data = await request.get('/words', { params: { keyword: query, page: 1, page_size: 20 } })
    mergeOptions.value = data.items
  } finally {
    mergeLoading.value = false
  }
}

async function doMerge() {
  if (!mergeTarget.value) return
  merging.value = true
  try {
    const r = await request.post('/words/merge', {
      keep_word_id: mergeTarget.value,
      remove_word_id: mergeRow.value.id
    })
    ElMessage.success(`已合并：迁移录音 ${r.moved_recordings} 条、领取 ${r.moved_claims} 条、任务条目 ${r.moved_items} 条，剔除冲突 ${r.removed_recordings + r.removed_claims + r.removed_items} 条`)
    mergeVisible.value = false
    load()
  } finally {
    merging.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除词条「${row.content}」吗？`, '提示', { type: 'warning' })
  await request.delete(`/words/${row.id}`)
  ElMessage.success('已删除')
  load()
}

/** 批量启用/禁用选中的词条 */
async function batchStatus(status) {
  const label = status === 'active' ? '启用' : '禁用'
  await ElMessageBox.confirm(`确定批量${label}选中的 ${selection.value.length} 个词条吗？`, '批量操作', { type: 'warning' })
  batchLoading.value = true
  try {
    const r = await request.post('/words/batch-status', { word_ids: selection.value, status })
    ElMessage.success(`已${label} ${r.processed} 条，跳过 ${r.skipped} 条（已处于目标状态或不在本省范围）`)
    clearSelection()
    load()
  } finally {
    batchLoading.value = false
  }
}

/** 批量删除选中的词条：有录音的跳过，不连带删录音 */
async function batchDelete() {
  await ElMessageBox.confirm(
    `确定批量删除选中的 ${selection.value.length} 个词条吗？若其中有词条已有录音将被跳过，不删除；在草稿/已发布任务中的将一并移出任务。`,
    '批量删除',
    { type: 'warning' }
  )
  batchLoading.value = true
  try {
    const r = await request.post('/words/batch-delete', { word_ids: selection.value })
    ElMessage.success(`已删除 ${r.processed} 条，跳过 ${r.skipped} 条（有录音）`)
    clearSelection()
    load()
  } finally {
    batchLoading.value = false
  }
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
  gap: 10px;
}
.total {
  color: #909399;
  font-size: 13px;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
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
.merge-tip {
  margin: 0 0 14px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
.actions-cell {
  display: flex;
  align-items: center;
  gap: 2px;
}
</style>

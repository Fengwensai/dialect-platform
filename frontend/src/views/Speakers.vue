<template>
  <div>
    <!-- 筛选栏 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="filter-bar">
        <el-select v-model="filterProvince" placeholder="全部省份" clearable filterable style="width: 180px">
          <el-option v-for="p in provinceOptions" :key="p.code" :label="p.name" :value="p.code" />
        </el-select>
        <el-input v-model="keyword" placeholder="搜索昵称 / 设备ID / openid" clearable style="width: 240px" @keyup.enter="load" />
        <el-select v-model="filterGender" placeholder="全部性别" clearable style="width: 120px">
          <el-option label="男" value="male" />
          <el-option label="女" value="female" />
          <el-option label="其他" value="other" />
        </el-select>
        <el-select v-model="filterAgeBracket" placeholder="全部年龄段" clearable style="width: 140px">
          <el-option v-for="(label, code) in AGE_LABELS" :key="code" :label="label" :value="code" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="load">查询</el-button>
        <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        <el-button type="success" :icon="Download" :loading="exporting" @click="exportDurations">导出时长</el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>
    </el-card>

    <!-- 发音人表格（el-table-v2 虚拟渲染，支持大列表流畅滚动） -->
    <el-card shadow="never">
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

    <!-- 编辑画像对话框（含属地纠错） -->
    <el-dialog v-model="editVisible" title="编辑发音人画像" width="460px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="属地">
          <div class="region-row">
            <el-select
              v-model="editForm.province_code"
              placeholder="省"
              filterable
              :disabled="!auth.isSuper"
              style="width: 33%"
              @change="onProvinceChange"
            >
              <el-option v-for="p in editProvinceOptions" :key="p.code" :label="p.name" :value="p.code" />
            </el-select>
            <el-select
              v-model="editForm.city_code"
              placeholder="市"
              filterable
              style="width: 33%"
              @change="onCityChange"
            >
              <el-option v-for="c in editCityOptions" :key="c.code" :label="c.name" :value="c.code" />
            </el-select>
            <el-select
              v-model="editForm.district_code"
              placeholder="区县"
              filterable
              clearable
              style="width: 33%"
            >
              <el-option v-for="d in editDistrictOptions" :key="d.code" :label="d.name" :value="d.code" />
            </el-select>
          </div>
          <div v-if="auth.isSuper" class="region-hint">修改属地会解除原团队绑定</div>
        </el-form-item>
        <el-form-item v-if="editForm.team_code" label="团队码">
          <el-tag type="warning" effect="plain">{{ editForm.team_code }}</el-tag>
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="editForm.gender" placeholder="请选择性别" clearable style="width: 100%">
            <el-option label="男" value="male" />
            <el-option label="女" value="female" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="年龄段">
          <el-select v-model="editForm.age_bracket" placeholder="请选择年龄段" clearable style="width: 100%">
            <el-option v-for="(label, code) in AGE_LABELS" :key="code" :label="label" :value="code" />
          </el-select>
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="editForm.nickname" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 合并发音人对话框 -->
    <el-dialog v-model="mergeVisible" title="合并发音人" width="540px">
      <p class="merge-tip">
        将把发音人 <b>「{{ mergeRow?.nickname || mergeRow?.device_id || ('#' + mergeRow?.id) }}」</b>（#{{ mergeRow?.id }}）合并到下方选中的目标发音人：
        其录音 / 领取 / 协议将转入目标，本发音人被删除。合并不可撤销。
      </p>
      <el-form label-width="70px">
        <el-form-item label="目标发音人">
          <el-select
            v-model="mergeTarget"
            placeholder="输入昵称 / 设备ID / openid 搜索"
            filterable
            remote
            clearable
            :remote-method="searchMergeSpeakers"
            :loading="mergeLoading"
            style="width: 100%"
          >
            <el-option
              v-for="s in mergeOptions"
              :key="s.id"
              :value="s.id"
              :disabled="s.id === mergeRow?.id"
              :label="`#${s.id} ${s.nickname || '(无昵称)'}${s.device_id ? '（' + s.device_id + '）' : ''}${s.province_code ? ' @' + regionName(s.province_code) : ''}`"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mergeVisible = false">取消</el-button>
        <el-button type="danger" :loading="merging" :disabled="!mergeTarget" @click="doMerge">合并</el-button>
      </template>
    </el-dialog>

    <!-- 录音明细对话框 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailTitle"
      width="900px"
      top="6vh"
      destroy-on-close
      :close-on-click-modal="false"
    >
      <div v-loading="detailLoading">
        <template v-if="detailSpeaker">
          <div class="detail-head">
            <span class="detail-name">{{ detailSpeaker.nickname || '-' }}</span>
            <span class="detail-sub">ID {{ detailSpeaker.id }}</span>
            <span v-if="detailSpeaker.device_id" class="detail-sub">设备 {{ detailSpeaker.device_id }}</span>
            <span v-if="detailSpeaker.province_code" class="detail-sub">
              {{ regionName(detailSpeaker.province_code) }}<template v-if="detailSpeaker.city_code">·{{ regionName(detailSpeaker.city_code) }}</template><template v-if="detailSpeaker.district_code">·{{ regionName(detailSpeaker.district_code) }}</template>
            </span>
            <span class="detail-sub">性别 {{ genderText(detailSpeaker.gender) }}</span>
            <span class="detail-sub">年龄段 {{ ageText(detailSpeaker.age_bracket) }}</span>
          </div>

          <!-- 贡献统计 -->
          <div v-if="detailStats" class="stats-row">
            <div class="stat-box">
              <div class="stat-num">{{ detailStats.total }}</div>
              <div class="stat-label">总录音</div>
            </div>
            <div class="stat-box warn">
              <div class="stat-num">{{ detailStats.pending }}</div>
              <div class="stat-label">待审核</div>
            </div>
            <div class="stat-box ok">
              <div class="stat-num">{{ detailStats.approved }}</div>
              <div class="stat-label">已通过</div>
            </div>
            <div class="stat-box bad">
              <div class="stat-num">{{ detailStats.rejected }}</div>
              <div class="stat-label">已驳回</div>
            </div>
            <div class="stat-box">
              <div class="stat-num">{{ fmtTotalDur(detailStats.total_duration_ms) }}</div>
              <div class="stat-label">总时长</div>
            </div>
            <div class="stat-box ok">
              <div class="stat-num">{{ fmtTotalDur(detailStats.approved_duration_ms) }}</div>
              <div class="stat-label">有效时长</div>
            </div>
            <div class="stat-box bad">
              <div class="stat-num">{{ fmtTotalDur(detailStats.rejected_duration_ms) }}</div>
              <div class="stat-label">无效时长</div>
            </div>
          </div>

          <!-- 按任务分布 -->
          <div v-if="detailStats && detailStats.tasks.length" class="task-row">
            <span class="task-label">任务分布：</span>
            <el-tag
              v-for="t in detailStats.tasks"
              :key="t.task_id"
              size="small"
              effect="plain"
              class="task-chip"
            >
              {{ t.task_name }} × {{ t.count }}
            </el-tag>
          </div>

          <!-- 筛选栏 -->
          <div class="filter-bar" style="margin: 12px 0 8px">
            <el-select v-model="detailTaskId" placeholder="全部任务" clearable filterable style="width: 250px">
              <el-option
                v-for="t in detailStats ? detailStats.tasks : []"
                :key="t.task_id"
                :label="t.task_name"
                :value="t.task_id"
              />
            </el-select>
            <el-select v-model="detailStatus" placeholder="状态" clearable style="width: 130px">
              <el-option label="待审核" value="pending" />
              <el-option label="已通过" value="approved" />
              <el-option label="已驳回" value="rejected" />
            </el-select>
            <el-button type="primary" size="small" @click="detailPage = 1; loadDetail()">查询</el-button>
            <el-button size="small" @click="resetDetail">重置</el-button>
            <el-button type="success" size="small" :loading="detailExporting" @click="exportDetail">导出明细</el-button>
            <el-button type="success" size="small" :loading="detailZipExporting" @click="exportDetailZip">导出录音(ZIP)</el-button>
            <span class="total">共 {{ detailTotal }} 条</span>
          </div>

          <!-- 录音列表 -->
          <el-table :data="detailItems" border stripe size="small">
            <el-table-column label="词条" min-width="140">
              <template #default="{ row }">
                <span class="word">{{ row.word_content }}</span>
                <span v-if="row.word_code" class="code">{{ row.word_code }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="task_name" label="任务" min-width="120" show-overflow-tooltip />
            <el-table-column label="状态" width="88">
              <template #default="{ row }">
                <el-tag :type="statusMeta[row.status]?.type || 'info'" size="small">
                  {{ statusMeta[row.status]?.label || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="音频" width="220">
              <template #default="{ row }">
                <audio controls :src="row.audio_url" preload="none" class="player-sm" />
              </template>
            </el-table-column>
            <el-table-column label="时长" width="70">
              <template #default="{ row }">{{ fmtDuration(row.audio_duration) }}</template>
            </el-table-column>
            <el-table-column prop="review_note" label="审核备注" min-width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ row.review_note || '-' }}</template>
            </el-table-column>
            <el-table-column label="提交时间" width="150">
              <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
            </el-table-column>
          </el-table>

          <el-pagination
            class="pager"
            background
            small
            layout="total, prev, pager, next"
            :total="detailTotal"
            :page-size="detailPageSize"
            :current-page="detailPage"
            @current-change="(p) => { detailPage = p; loadDetail() }"
          />
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, h, onMounted, reactive, ref } from 'vue'
import { ElButton, ElMessage, ElMessageBox, ElTag, ElTooltip } from 'element-plus'
import { Search, RefreshLeft, Download } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'
import { useRegionStore } from '../stores/regions'
import { downloadFile } from '../utils/download'
import { usePersistedFilters } from '../composables/usePersistedFilters'

const GENDER_LABELS = { male: '男', female: '女', other: '其他' }
const AGE_LABELS = { under18: '<18', age18_30: '18-30', age31_45: '31-45', age46_60: '46-60', over60: '>60' }

const auth = useAuthStore()
const regionStore = useRegionStore()
const loading = ref(false)
const saving = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1) // 页码不持久化（刷新回第 1 页）
// 筛选条件本地持久化（后台完善 9）：刷新/重进不丢；reset() 把值设回默认即清空
const { pageSize, keyword, filterProvince, filterGender, filterAgeBracket } =
  usePersistedFilters('speakers-filters-v1', {
    pageSize: 20,
    keyword: '',
    filterProvince: '',
    filterGender: '',
    filterAgeBracket: ''
  })

const editVisible = ref(false)
const editForm = reactive({ id: null, nickname: '', gender: '', age_bracket: '', province_code: '', city_code: '', district_code: '', team_code: '' })
const origProvince = ref('')
const origCity = ref('')
const origDistrict = ref('')

const mergeVisible = ref(false)
const mergeRow = ref(null)
const mergeOptions = ref([])
const mergeTarget = ref(null)
const mergeLoading = ref(false)
const merging = ref(false)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailSpeaker = ref(null)
const detailStats = ref(null)
const detailItems = ref([])
const detailTotal = ref(0)
const detailPage = ref(1)
const detailPageSize = ref(20)
const detailTaskId = ref(null)
const detailStatus = ref('')
const exporting = ref(false)
const detailExporting = ref(false)
const detailZipExporting = ref(false)

const statusMeta = {
  pending: { type: 'warning', label: '待审核' },
  approved: { type: 'success', label: '已通过' },
  rejected: { type: 'danger', label: '已驳回' }
}

const detailTitle = computed(() =>
  detailSpeaker.value
    ? `录音明细 — ${detailSpeaker.value.nickname || ('#' + detailSpeaker.value.id)}`
    : '录音明细'
)

const provinceOptions = computed(() => regionStore.tree)

// 编辑弹窗：省下拉（省管理员锁定本省）、市下拉（跟随所选省）
const editProvinceOptions = computed(() => {
  if (auth.isSuper) return regionStore.tree
  const locked = auth.provinceCode
  return locked ? (regionStore.tree || []).filter((p) => p.code === locked) : []
})

const editCityOptions = computed(() => {
  const p = (regionStore.tree || []).find((x) => x.code === editForm.province_code)
  return (p && p.children) || []
})

const editDistrictOptions = computed(() => {
  const p = (regionStore.tree || []).find((x) => x.code === editForm.province_code)
  const c = p && (p.children || []).find((x) => x.code === editForm.city_code)
  return (c && c.children) || []
})

function onProvinceChange() {
  editForm.city_code = ''
  editForm.district_code = ''
}

function onCityChange() {
  editForm.district_code = ''
}

function regionName(code) {
  return regionStore.nameOf(code)
}

function genderText(code) {
  return code ? (GENDER_LABELS[code] || code) : '-'
}

function ageText(code) {
  return code ? (AGE_LABELS[code] || code) : '-'
}

function fmtDuration(ms) {
  if (!ms) return '-'
  return (ms / 1000).toFixed(1) + 's'
}

function fmtTotalDur(ms) {
  if (!ms) return '0'
  const s = Math.round(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h) return `${h}时${m}分`
  if (m) return `${m}分${sec}秒`
  return `${sec}秒`
}

function pct(v) {
  if (v == null || isNaN(v)) return '-'
  return (v * 100).toFixed(0) + '%'
}

// el-table-v2 列配置（cellRenderer 返回 VNode，渲染自定义单元格）
// 注意：cellRenderer 收到的 props 是 { rowData, rowIndex, ... }（无 row），
// 自定义单元格一律从 rowData 取字段。
const columns = computed(() => [
  { key: 'id', dataKey: 'id', title: 'ID', width: 60 },
  { key: 'nickname', dataKey: 'nickname', title: '昵称', width: 120, showOverflowTooltip: true },
  { key: 'device_id', dataKey: 'device_id', title: '设备ID', width: 170, showOverflowTooltip: true },
  { key: 'openid', dataKey: 'openid', title: 'openid', width: 170, showOverflowTooltip: true },
  {
    key: 'region',
    title: '属地',
    width: 160,
    cellRenderer: ({ rowData }) => {
      if (!rowData.province_code) return h(ElTag, { type: 'info', size: 'small' }, () => '未绑定')
      const parts = [regionName(rowData.province_code)]
      if (rowData.city_code) parts.push(regionName(rowData.city_code))
      if (rowData.district_code) parts.push(regionName(rowData.district_code))
      return parts.join('·')
    }
  },
  {
    key: 'team_code',
    title: '团队码',
    width: 110,
    cellRenderer: ({ rowData }) => (rowData.team_code ? h(ElTag, { type: 'warning', effect: 'plain', size: 'small' }, () => rowData.team_code) : '-')
  },
  {
    key: 'gender',
    title: '性别',
    width: 90,
    cellRenderer: ({ rowData }) => genderText(rowData.gender)
  },
  {
    key: 'age_bracket',
    title: '年龄段',
    width: 100,
    cellRenderer: ({ rowData }) => ageText(rowData.age_bracket)
  },
  { key: 'recording_count', dataKey: 'recording_count', title: '录音数', width: 80 },
  {
    key: 'quality',
    title: '质量',
    width: 110,
    cellRenderer: ({ rowData }) => {
      if (rowData.upload_paused) return h(ElTag, { type: 'danger', size: 'small' }, () => '已暂停')
      if (rowData.quality_warned) {
        return h(ElTooltip,
          { content: `通过率 ${pct(rowData.approval_rate)}（已审核 ${rowData.reviewed_total} 条）`, placement: 'top' },
          () => h(ElTag, { type: 'warning', size: 'small' }, () => '低质预警'))
      }
      return h('span', { class: 'tr-empty' }, '-')
    }
  },
  {
    key: 'created_at',
    title: '建档时间',
    width: 150,
    cellRenderer: ({ rowData }) => rowData.created_at?.slice(0, 16) || '-'
  },
  {
    key: 'actions',
    title: '操作',
    width: 320,
    fixed: 'right',
    cellRenderer: ({ rowData }) =>
      h('div', { class: 'actions-cell' }, [
        h(ElButton, { link: true, type: 'primary', onClick: () => openDetail(rowData) }, () => '明细'),
        h(ElButton, { link: true, type: 'primary', onClick: () => openEdit(rowData) }, () => '编辑'),
        h(ElButton, { link: true, type: 'warning', onClick: () => openMerge(rowData) }, () => '合并'),
        h(ElButton, { link: true, type: rowData.upload_paused ? 'success' : 'warning', onClick: () => togglePause(rowData) }, () => rowData.upload_paused ? '恢复上传' : '暂停上传'),
        h(ElButton, { link: true, type: 'danger', onClick: () => removeSpeaker(rowData) }, () => '删除')
      ])
  }
])

async function load() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      province_code: filterProvince.value || undefined,
      gender: filterGender.value || undefined,
      age_bracket: filterAgeBracket.value || undefined
    }
    const data = await request.get('/speakers', { params })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function reset() {
  keyword.value = ''
  filterProvince.value = ''
  filterGender.value = ''
  filterAgeBracket.value = ''
  page.value = 1
  load()
}

async function openDetail(row) {
  detailSpeaker.value = row
  detailPage.value = 1
  detailTaskId.value = null
  detailStatus.value = ''
  detailVisible.value = true
  await loadDetail()
}

async function loadDetail() {
  if (!detailSpeaker.value) return
  detailLoading.value = true
  try {
    const params = { page: detailPage.value, page_size: detailPageSize.value }
    if (detailTaskId.value) params.task_id = detailTaskId.value
    if (detailStatus.value) params.status = detailStatus.value
    const data = await request.get(`/speakers/${detailSpeaker.value.id}/recordings`, { params })
    detailItems.value = data.items
    detailTotal.value = data.total
    detailStats.value = data.stats
  } finally {
    detailLoading.value = false
  }
}

function resetDetail() {
  detailTaskId.value = null
  detailStatus.value = ''
  detailPage.value = 1
  loadDetail()
}

/** 导出发音人时长汇总 CSV（遵循当前筛选条件） */
async function exportDurations() {
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (filterProvince.value) params.set('province_code', filterProvince.value)
  if (filterGender.value) params.set('gender', filterGender.value)
  if (filterAgeBracket.value) params.set('age_bracket', filterAgeBracket.value)
  const qs = params.toString()
  await downloadFile(
    qs ? `/api/speakers/export?${qs}` : '/api/speakers/export',
    `speakers_duration_${Date.now()}.csv`,
    exporting
  )
}

/** 导出发音人录音明细 CSV（遵循当前任务/状态筛选） */
async function exportDetail() {
  if (!detailSpeaker.value) return
  const params = new URLSearchParams()
  if (detailTaskId.value) params.set('task_id', detailTaskId.value)
  if (detailStatus.value) params.set('status', detailStatus.value)
  const qs = params.toString()
  const base = `/api/speakers/${detailSpeaker.value.id}/recordings/export`
  await downloadFile(
    qs ? `${base}?${qs}` : base,
    `speaker_${detailSpeaker.value.id}_recordings_${Date.now()}.csv`,
    detailExporting
  )
}

/** 导出发音人全部录音 ZIP（含驳回/待审，遵循当前任务/状态筛选） */
async function exportDetailZip() {
  if (!detailSpeaker.value) return
  const params = new URLSearchParams()
  if (detailTaskId.value) params.set('task_id', detailTaskId.value)
  if (detailStatus.value) params.set('status', detailStatus.value)
  params.set('format', 'zip')
  const qs = params.toString()
  await downloadFile(
    `/api/speakers/${detailSpeaker.value.id}/recordings/export?${qs}`,
    `speaker_${detailSpeaker.value.id}_recordings_${Date.now()}.zip`,
    detailZipExporting
  )
}

function openEdit(row) {
  // 省管理员只能在所属省内纠错：未绑定属地的发音人默认落到本省
  let province = row.province_code || ''
  if (!auth.isSuper && !province && auth.provinceCode) province = auth.provinceCode
  Object.assign(editForm, {
    id: row.id,
    nickname: row.nickname || '',
    gender: row.gender || '',
    age_bracket: row.age_bracket || '',
    province_code: province,
    city_code: row.city_code || '',
    district_code: row.district_code || '',
    team_code: row.team_code || ''
  })
  origProvince.value = row.province_code || ''
  origCity.value = row.city_code || ''
  origDistrict.value = row.district_code || ''
  editVisible.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = {
      gender: editForm.gender || null,
      age_bracket: editForm.age_bracket || null
    }
    // 属地纠错：仅提交发生变化的字段（省管理员不能越省）
    if (editForm.province_code !== origProvince.value) payload.province_code = editForm.province_code
    if (editForm.city_code !== origCity.value) payload.city_code = editForm.city_code
    if (editForm.district_code !== origDistrict.value) payload.district_code = editForm.district_code
    await request.patch(`/speakers/${editForm.id}`, payload)
    ElMessage.success('已保存')
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function removeSpeaker(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除发音人「${row.nickname || row.device_id || row.id}」？删除后不可恢复，其头像与领取记录一并删除；有录音的发音人无法删除。`,
      '删除确认',
      { type: 'warning', confirmButtonClass: 'el-button--danger' }
    )
  } catch (e) { return }
  await request.delete(`/speakers/${row.id}`)
  ElMessage.success('已删除')
  load()
}

// 质量预警（后台完善 3）：一键暂停/恢复上传。暂停弹确认（影响发音人操作），恢复直接执行。
async function togglePause(row) {
  const pause = !row.upload_paused
  if (pause) {
    try {
      await ElMessageBox.confirm(
        `确定暂停「${row.nickname || row.device_id || row.id}」的上传吗？暂停后该发音人无法再上传录音（可随时恢复）。`,
        '暂停上传',
        { type: 'warning', confirmButtonClass: 'el-button--danger' }
      )
    } catch (e) { return }
  }
  await request.patch(`/speakers/${row.id}`, { upload_paused: pause })
  ElMessage.success(pause ? '已暂停上传' : '已恢复上传')
  load()
}

function openMerge(row) {
  mergeRow.value = row
  mergeTarget.value = null
  mergeOptions.value = []
  mergeVisible.value = true
}

async function searchMergeSpeakers(query) {
  if (!query) {
    mergeOptions.value = []
    return
  }
  mergeLoading.value = true
  try {
    const data = await request.get('/speakers', { params: { keyword: query, page: 1, page_size: 20 } })
    mergeOptions.value = data.items
  } finally {
    mergeLoading.value = false
  }
}

async function doMerge() {
  if (!mergeTarget.value) return
  merging.value = true
  try {
    const r = await request.post('/speakers/merge', {
      keep_speaker_id: mergeTarget.value,
      remove_speaker_id: mergeRow.value.id
    })
    ElMessage.success(`已合并：迁移录音 ${r.moved_recordings} 条、领取 ${r.moved_claims} 条、协议 ${r.moved_agreements} 条，剔除冲突 ${r.removed_recordings + r.removed_claims + r.removed_agreements} 条`)
    mergeVisible.value = false
    load()
  } finally {
    merging.value = false
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
  flex-wrap: wrap;
}
.total {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.muted {
  color: var(--el-text-color-placeholder);
}
.region-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.region-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.actions-cell {
  display: flex;
  align-items: center;
  gap: 2px;
}
.detail-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}
.detail-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.detail-sub {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.stats-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.stat-box {
  flex: 1;
  padding: 10px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  text-align: center;
}
.stat-num {
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.stat-box.warn .stat-num { color: #e6a23c; }
.stat-box.ok .stat-num { color: #67c23a; }
.stat-box.bad .stat-num { color: #f56c6c; }
.stat-label {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.task-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 4px;
}
.task-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.word {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.code {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.player-sm {
  width: 210px;
  height: 32px;
  vertical-align: middle;
}
.merge-tip {
  margin: 0 0 14px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
</style>

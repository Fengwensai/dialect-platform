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
        <el-checkbox v-model="filterQuality" style="margin-right: 4px" @change="page = 1; load()">
          只看疑似无效
        </el-checkbox>
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

        <!-- 快捷键模式开关 + 帮助 -->
        <el-switch
          v-model="shortcutMode"
          active-text="快捷键"
          inactive-text="快捷键"
          inline-prompt
          style="--el-switch-on-color: #409eff"
          @change="onShortcutToggle"
        />
        <el-popover placement="bottom" :width="340" trigger="click" popper-class="keys-help">
          <template #reference>
            <el-button :icon="QuestionFilled" circle size="small" title="快捷键帮助" />
          </template>
          <div class="keys-help">
            <div class="kh-title">审核快捷键（当前：{{ shortcutMode ? '开启' : '关闭' }}）</div>
            <div class="kh-row"><span class="kbd">空格</span><span>播放 / 暂停当前单</span></div>
            <div class="kh-row"><span class="kbd">→</span><span class="kbd">N</span><span>下一单</span></div>
            <div class="kh-row"><span class="kbd">←</span><span class="kbd">P</span><span>上一单</span></div>
            <div class="kh-row"><span class="kbd">A</span><span>通过当前单（免确认快审）</span></div>
            <div class="kh-row"><span class="kbd">R</span><span>驳回当前单（用底部勾选的原因）</span></div>
            <div class="kh-row"><span class="kbd">T</span><span>编辑当前单转写</span></div>
            <div class="kh-row"><span class="kbd">G</span><span>切换「审后自动播放下一条」</span></div>
            <div class="kh-row"><span class="kbd">Esc</span><span>停止播放 / 关闭弹窗</span></div>
            <div class="kh-tip">输入框 / 弹窗打开时仅 Esc 生效；下方可滚动区域的音频用单播放器试听。</div>
          </div>
        </el-popover>
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
        ref="tableRef"
        :data="items"
        v-loading="loading"
        border
        stripe
        row-key="id"
        highlight-current-row
        @selection-change="onSelectionChange"
        @current-change="onCurrentChange"
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
        <el-table-column label="音频" width="90">
          <template #default="{ row }">
            <el-button link type="primary" :icon="VideoPlay" @click="setCurrentRow(row, { play: true })">试听</el-button>
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
        <el-table-column label="质量" width="100">
          <template #default="{ row }">
            <el-tooltip v-if="row.quality_status === 'suspect'" :content="qualityTip(row)" placement="top">
              <el-tag type="danger" size="small" effect="plain">疑似无效</el-tag>
            </el-tooltip>
            <span v-else class="tr-empty">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type || 'info'" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="驳回原因/备注" min-width="160">
          <template #default="{ row }">
            <template v-if="row.reject_reasons">
              <el-tag
                v-for="t in rejectReasonTags(row)"
                :key="t"
                type="danger"
                size="small"
                effect="plain"
                class="rr-tag"
              >{{ t }}</el-tag>
            </template>
            <span v-if="row.review_note" class="rr-note">{{ row.review_note }}</span>
            <span v-if="!row.reject_reasons && !row.review_note" class="tr-empty">-</span>
          </template>
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
            <el-button v-if="row.status !== 'approved'" link type="success" @click="fastApprove(row)">通过</el-button>
            <el-button v-if="row.status !== 'rejected'" link type="danger" @click="fastReject(row)">驳回</el-button>
            <template v-if="row.status === 'rejected'">
              <el-button link type="warning" :icon="RefreshLeft" @click="resetReview(row)">重置</el-button>
              <el-button link type="danger" :icon="Delete" @click="removeRecording(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <!-- 当前单播放器栏（单播放器 + 快审） -->
      <div v-if="currentRow" class="player-bar">
        <div class="pb-info">
          <el-tag size="small" :type="statusMeta[currentRow.status]?.type || 'info'">
            {{ statusMeta[currentRow.status]?.label || currentRow.status }}
          </el-tag>
          <span class="pb-word">{{ currentRow.word_content }}</span>
          <span class="pb-sub">{{ currentRow.speaker_nickname || currentRow.speaker_device || '-' }}</span>
          <span class="pb-sub">{{ fmtDuration(currentRow.audio_duration) }}</span>
          <span class="pb-sub">#{{ currentRow.id }}</span>
        </div>
        <audio
          ref="audioRef"
          :src="currentRow.audio_url"
          preload="metadata"
          class="pb-audio"
          @canplay="onCanplay"
          @ended="onEnded"
        />
        <div class="pb-actions">
          <el-button size="small" :icon="VideoPlay" @click="togglePlay">播放/暂停</el-button>
          <el-select
            v-model="rejectReasons"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="驳回原因（多选）"
            clearable
            size="small"
            class="pb-reasons"
            @keydown.stop
          >
            <el-option v-for="r in REJECT_REASON_OPTIONS" :key="r.key" :label="r.label" :value="r.key" />
          </el-select>
          <el-input
            v-model="rejectNote"
            size="small"
            placeholder="备注（可选）"
            clearable
            class="pb-note"
            @keydown.stop
          />
          <el-button
            size="small"
            type="success"
            :disabled="currentRow.status === 'approved'"
            @click="fastApprove()"
          >通过</el-button>
          <el-button
            size="small"
            type="danger"
            :disabled="currentRow.status === 'rejected'"
            @click="fastReject()"
          >驳回</el-button>
          <el-button size="small" @click="openTrans(currentRow)">转写</el-button>
          <el-switch v-model="autoPlayNext" active-text="自动播下一条" inline-prompt size="small" />
        </div>
      </div>

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

      <!-- 批量驳回弹窗（原因多选 + 备注，后台完善 2） -->
      <el-dialog v-model="batchDialog.visible" title="批量驳回" width="480px" :close-on-click-modal="false">
        <div class="bb-tip">已选 <b class="sel-count">{{ selection.length }}</b> 条待审核录音，将统一驳回。</div>
        <div class="bb-field">
          <div class="bb-label">驳回原因（多选，可空）</div>
          <el-select
            v-model="batchDialog.reasons"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择驳回原因"
            style="width: 100%"
          >
            <el-option v-for="r in REJECT_REASON_OPTIONS" :key="r.key" :label="r.label" :value="r.key" />
          </el-select>
        </div>
        <div class="bb-field">
          <div class="bb-label">备注（可空）</div>
          <el-input v-model="batchDialog.note" placeholder="统一备注，如：这批录音背景噪音大" clearable />
        </div>
        <template #footer>
          <el-button @click="batchDialog.visible = false">取消</el-button>
          <el-button
            type="danger"
            :loading="batchLoading"
            @click="doBatch(false, batchDialog.note || null, batchDialog.reasons)"
          >确认驳回</el-button>
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
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, RefreshLeft, Download, CircleCheck, CircleClose, Delete, VideoPlay, QuestionFilled } from '@element-plus/icons-vue'
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

// 录音质量预检旗标中文化（后台完善 1）
const QUALITY_FLAG_LABELS = {
  too_short: '录音过短',
  silent: '静音无声',
  too_quiet: '音量过低'
}

// 驳回原因固定选项（后台完善 2，key 与后端 core/reject_reasons.py 一致）
const REJECT_REASON_OPTIONS = [
  { key: 'noise', label: '背景噪音' },
  { key: 'misread', label: '念错' },
  { key: 'too_quiet', label: '音量太小' },
  { key: 'mandarin', label: '普通话混读' },
  { key: 'incomplete', label: '不完整' },
  { key: 'other', label: '其他' }
]
const REJECT_REASON_LABELS = Object.fromEntries(REJECT_REASON_OPTIONS.map((r) => [r.key, r.label]))

function rejectReasonTags(row) {
  return (row.reject_reasons || '').split(',').filter(Boolean).map((k) => REJECT_REASON_LABELS[k] || k)
}

function qualityTip(row) {
  const parts = (row.quality_flags || '')
    .split(',')
    .filter(Boolean)
    .map((f) => QUALITY_FLAG_LABELS[f] || f)
  const m = row.quality_metrics
  if (m && m.duration_ms != null) parts.push(`时长 ${(m.duration_ms / 1000).toFixed(1)}s`)
  return parts.join('、') || '疑似无效'
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
const filterQuality = ref(false) // 只看疑似无效
const filterKeyword = ref('')
const filterProvince = ref('')
const sortBy = ref('pending_first')
const selection = ref([])
const taskOptions = ref([])
const transDialog = ref({ visible: false, id: null, word: '', mandarin: '', dialect: '' })
const batchDialog = ref({ visible: false, reasons: [], note: '' }) // 批量驳回：原因多选 + 备注
const savingTrans = ref(false)

// 当前单 + 单播放器状态
const tableRef = ref(null)
const audioRef = ref(null)
const currentId = ref(null)
const pendingPlay = ref(false) // 设置 src 后等待 canplay 再自动播放，避免竞态
const shortcutMode = ref(true) // 快捷键模式开关，默认开
const autoPlayNext = ref(true) // 审后自动播放下一条
const rejectNote = ref('') // 快审驳回备注（底部栏输入）
const rejectReasons = ref([]) // 快审驳回原因（底部栏多选，key 列表）

const currentRow = computed(() => items.value.find((r) => r.id === currentId.value) || null)

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

async function load(onDone) {
  loading.value = true
  // 刷新即清空当前行/播放，避免残留高亮指向已不存在的行
  currentId.value = null
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filterTaskId.value) params.task_id = filterTaskId.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterQuality.value) params.quality = 'suspect'
    if (filterKeyword.value) params.keyword = filterKeyword.value
    if (filterProvince.value) params.province_code = filterProvince.value
    if (sortBy.value) params.sort_by = sortBy.value
    const data = await request.get('/review/recordings', { params })
    items.value = data.items
    total.value = data.total
    selection.value = [] // 翻页/刷新后清空勾选，避免残留
    tableRef.value?.setCurrentRow(null)
  } finally {
    loading.value = false
    onDone?.()
  }
}

function reset() {
  filterTaskId.value = null
  filterStatus.value = 'pending'
  filterQuality.value = false
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

/* ---------- 当前行 + 单播放器 ---------- */

function onCurrentChange(row) {
  currentId.value = row?.id ?? null
}

/** 设置当前行；opts.play 为 true 时在音频就绪后自动播放 */
function setCurrentRow(row, opts) {
  stopAudio()
  currentId.value = row?.id ?? null
  pendingPlay.value = !!(opts && opts.play)
  nextTick(() => tableRef.value?.setCurrentRow(row))
}

function stopAudio() {
  const a = audioRef.value
  if (a) {
    a.pause()
    a.currentTime = 0
  }
  pendingPlay.value = false
}

function togglePlay() {
  const r = currentRow.value
  if (!r) {
    const first = items.value[0]
    if (first) setCurrentRow(first, { play: true })
    return
  }
  const a = audioRef.value
  if (!a) return
  if (a.paused) {
    if (a.readyState >= 2) {
      a.play()
    } else {
      pendingPlay.value = true
      a.load()
    }
  } else {
    a.pause()
  }
}

function onCanplay() {
  if (pendingPlay.value) {
    pendingPlay.value = false
    audioRef.value?.play()
  }
}

function onEnded() {
  if (autoPlayNext.value) moveCurrent(1)
}

/** 按方向移动当前单；越过本页边界时自动翻页并定位首/末行 */
function moveCurrent(delta) {
  const list = items.value
  if (!list.length) return
  const idx = list.findIndex((r) => r.id === currentId.value)
  const ni = idx === -1 ? 0 : idx + delta
  if (ni >= 0 && ni < list.length) {
    setCurrentRow(list[ni], { play: autoPlayNext.value })
    return
  }
  const nextPage = page.value + delta
  if (nextPage < 1 || (nextPage - 1) * pageSize.value >= total.value) return
  page.value = nextPage
  const wantFirst = delta > 0
  load(() => {
    const r = wantFirst ? items.value[0] : items.value[items.value.length - 1]
    if (r) setCurrentRow(r, { play: autoPlayNext.value })
  })
}

/* ---------- 快审（免确认，判后自动推进） ---------- */

async function fastApprove(row) {
  const r = row || currentRow.value
  if (!r || r.status === 'approved') return
  setCurrentRow(r)
  try {
    await request.post(`/review/recordings/${r.id}/verdict`, { approved: true })
    ElMessage.success(`已通过 #${r.id}`)
  } catch (e) {
    return
  }
  removeAndAdvance(r)
}

async function fastReject(row) {
  const r = row || currentRow.value
  if (!r || r.status === 'rejected') return
  setCurrentRow(r)
  try {
    const payload = {
      approved: false,
      reasons: rejectReasons.value.length ? [...rejectReasons.value] : null,
      note: rejectNote.value || null
    }
    await request.post(`/review/recordings/${r.id}/verdict`, payload)
    ElMessage.success(`已驳回 #${r.id}`)
  } catch (e) {
    return
  }
  removeAndAdvance(r)
}

/** 从列表剔除已判行、总数减一、游标推进到下一行；本页审空自动翻页 */
function removeAndAdvance(r) {
  const list = items.value
  const idx = list.findIndex((x) => x.id === r.id)
  selection.value = selection.value.filter((x) => x.id !== r.id)
  if (idx !== -1) {
    list.splice(idx, 1)
    total.value--
  }
  if (list.length) {
    const next = list[Math.min(idx, list.length - 1)]
    setCurrentRow(next, { play: autoPlayNext.value })
  } else if (page.value * pageSize.value < total.value) {
    page.value++
    load(() => {
      const first = items.value[0]
      if (first) setCurrentRow(first, { play: autoPlayNext.value })
    })
  } else if (page.value > 1 && (page.value - 1) * pageSize.value >= total.value) {
    page.value--
    load(() => {
      const last = items.value[items.value.length - 1]
      if (last) setCurrentRow(last, { play: autoPlayNext.value })
    })
  } else {
    currentId.value = null
  }
}

/* ---------- 快捷键 ---------- */

function onShortcutToggle(val) {
  if (!val) stopAudio()
  ElMessage.info(val ? '快捷键已开启' : '快捷键已关闭')
}

function onKeydown(e) {
  if (!shortcutMode.value) return
  if (e.ctrlKey || e.metaKey || e.altKey) return
  const tag = (e.target && e.target.tagName) || ''
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)

  // 弹窗打开时只允许 Esc 关闭
  if (transDialog.value.visible || batchDialog.value.visible) {
    if (e.key === 'Escape') {
      e.preventDefault()
      if (transDialog.value.visible) transDialog.value.visible = false
      else batchDialog.value.visible = false
    }
    return
  }
  // 输入框内不劫持按键
  if (typing) return

  switch (e.key) {
    case ' ':
      e.preventDefault()
      togglePlay()
      break
    case 'ArrowRight':
    case 'n':
    case 'N':
      e.preventDefault()
      moveCurrent(1)
      break
    case 'ArrowLeft':
    case 'p':
    case 'P':
      e.preventDefault()
      moveCurrent(-1)
      break
    case 'a':
    case 'A':
      e.preventDefault()
      fastApprove()
      break
    case 'r':
    case 'R':
      e.preventDefault()
      fastReject()
      break
    case 't':
    case 'T':
      e.preventDefault()
      if (currentRow.value) openTrans(currentRow.value)
      break
    case 'g':
    case 'G':
      autoPlayNext.value = !autoPlayNext.value
      ElMessage.info(autoPlayNext.value ? '已开启审后自动播放下一条' : '已关闭审后自动播放下一条')
      break
    case 'Escape':
      e.preventDefault()
      stopAudio()
      break
  }
}

/* ---------- 批量 / 重置 / 删除（保留确认框） ---------- */

async function batchApprove() {
  const n = selection.value.length
  await ElMessageBox.confirm(`确定批量通过选中的 ${n} 条录音吗？`, '批量通过', { type: 'success' })
  await doBatch(true, null, null)
}

function batchReject() {
  // 打开批量驳回弹窗（原因多选 + 备注），确认后统一驳回
  batchDialog.value.reasons = []
  batchDialog.value.note = ''
  batchDialog.value.visible = true
}

async function doBatch(approved, note, reasons) {
  batchLoading.value = true
  try {
    const ids = selection.value.map((r) => r.id)
    const data = await request.post('/review/batch-verdict', {
      recording_ids: ids,
      approved,
      reasons: reasons && reasons.length ? [...reasons] : null,
      note
    })
    ElMessage.success(`已处理 ${data.processed} 条${data.skipped ? `，跳过已审 ${data.skipped} 条` : ''}`)
    selection.value = []
    batchDialog.value.visible = false
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
  window.addEventListener('keydown', onKeydown)
  load()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
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
/* 当前单播放器栏 */
.player-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 14px;
  padding: 10px 14px;
  background: #f0f9ff;
  border: 1px solid #c6e2ff;
  border-radius: 8px;
}
.pb-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 260px;
}
.pb-word {
  font-weight: 600;
  color: #303133;
}
.pb-sub {
  font-size: 12px;
  color: #909399;
}
.pb-audio {
  width: 300px;
  height: 36px;
}
.pb-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.pb-note {
  width: 200px;
}
.pb-reasons {
  width: 230px;
}
.rr-tag {
  margin-right: 4px;
}
.rr-note {
  margin-left: 4px;
  color: #606266;
  font-size: 13px;
}
.bb-tip {
  margin-bottom: 12px;
  color: #606266;
}
.bb-field {
  margin-bottom: 12px;
}
.bb-label {
  margin-bottom: 6px;
  font-size: 13px;
  color: #606266;
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

<style>
/* 帮助 popover（非 scoped：popover 挂载到 body） */
.keys-help .kh-title {
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.keys-help .kh-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 13px;
  color: #606266;
}
.keys-help .kbd {
  display: inline-block;
  min-width: 20px;
  padding: 1px 6px;
  border: 1px solid #dcdfe6;
  border-bottom-width: 2px;
  border-radius: 4px;
  background: #fff;
  font-family: inherit;
  font-size: 12px;
  text-align: center;
  color: #303133;
}
.keys-help .kh-tip {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
</style>

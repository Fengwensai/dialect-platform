<template>
  <div class="task-detail">
    <div class="detail-top">
      <el-button link type="primary" :icon="Back" @click="$router.back()">返回任务列表</el-button>
      <el-tag v-if="task?.is_demo" size="small" type="warning" style="margin-left: 4px">演示</el-tag>
    </div>

    <!-- 任务信息卡 -->
    <el-card v-loading="taskLoading" class="task-card">
      <div class="task-head">
        <div class="task-title">
          <span class="title-text">{{ task?.name || '-' }}</span>
          <el-tag v-if="task" size="small" :type="statusTag(task.status)">{{ statusLabel(task.status) }}</el-tag>
        </div>
        <div v-if="task" class="task-summary">
          <span class="chip">参与发音人 <b>{{ summary.speaker_count }}</b> 人</span>
          <span class="chip">有效录音 <b>{{ summary.approved_total }}</b> 条</span>
          <span class="chip">有效时长 <b>{{ fmtDuration(summary.valid_duration_ms) }}</b></span>
        </div>
      </div>
      <el-descriptions v-if="task" :column="4" border size="small" class="task-info">
        <el-descriptions-item label="投放区划">
          {{ regionName(task.province_code) }}{{ task.city_code ? '-' + regionName(task.city_code) : '' }}{{ task.district_code ? '-' + regionName(task.district_code) : '' }}
        </el-descriptions-item>
        <el-descriptions-item label="关联团队">
          <span v-if="task.team_code">{{ task.team_code }}</span>
          <span v-else class="muted">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="词条数">{{ task.word_count }}</el-descriptions-item>
        <el-descriptions-item label="必录数">{{ task.required_audio_count }}</el-descriptions-item>
        <el-descriptions-item label="领取上限">{{ task.claim_limit }}</el-descriptions-item>
        <el-descriptions-item label="截止时间">{{ fmtDeadline(task.deadline_at) }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ fmtTime(task.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="任务进度">
          <el-progress
            :percentage="task.word_count ? Math.round((task.recorded_count / task.word_count) * 100) : 0"
            :status="task.recorded_count >= task.word_count ? 'success' : undefined"
            style="width: 160px"
          />
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 筛选 + 导出 -->
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="昵称/设备ID"
        clearable
        style="width: 200px"
        @keyup.enter="page = 1; loadContributors()"
      />
      <el-input
        v-model="teamCode"
        placeholder="团队码"
        clearable
        style="width: 140px"
        @keyup.enter="page = 1; loadContributors()"
      />
      <el-button type="primary" :icon="Search" @click="page = 1; loadContributors()">查询</el-button>
      <el-button :icon="RefreshLeft" @click="resetFilters">重置</el-button>
      <el-button type="success" :icon="Download" :loading="exporting" @click="exportTask">导出CSV</el-button>
      <span class="total">共 {{ total }} 名发音人</span>
    </div>

    <!-- 发音人贡献表 -->
    <el-table :data="items" v-loading="loading" border>
      <el-table-column prop="speaker_id" label="发音人ID" width="90" />
      <el-table-column label="团队码" width="110">
        <template #default="{ row }">
          <span v-if="row.team_code">{{ row.team_code }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="team_name" label="团队名" width="140">
        <template #default="{ row }">
          <span v-if="row.team_name">{{ row.team_name }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="nickname" label="昵称" min-width="110">
        <template #default="{ row }">
          <span v-if="row.nickname">{{ row.nickname }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="device_id" label="设备ID" min-width="130">
        <template #default="{ row }">
          <span v-if="row.device_id">{{ row.device_id }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="属地" width="150">
        <template #default="{ row }">{{ [row.province_name, row.city_name, row.district_name].filter(Boolean).join('-') || '-' }}</template>
      </el-table-column>
      <el-table-column prop="recording_total" label="录音总数" width="90" />
      <el-table-column prop="pending" label="待审" width="65" />
      <el-table-column prop="approved" label="通过" width="65" />
      <el-table-column prop="rejected" label="驳回" width="65" />
      <el-table-column label="有效时长" width="105">
        <template #default="{ row }">{{ fmtDuration(row.valid_duration_ms) }}</template>
      </el-table-column>
      <el-table-column label="总时长" width="95">
        <template #default="{ row }">{{ fmtDuration(row.total_duration_ms) }}</template>
      </el-table-column>
      <el-table-column label="通过率" width="80">
        <template #default="{ row }">{{ pct(row.approval_rate) }}</template>
      </el-table-column>
      <el-table-column label="最近提交" width="160">
        <template #default="{ row }">{{ fmtTime(row.last_active) }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      background
      layout="total, prev, pager, next, sizes"
      :page-sizes="[10, 20, 50, 100]"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      @current-change="p => { page = p; loadContributors() }"
      @size-change="s => { pageSize = s; page = 1; loadContributors() }"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, RefreshLeft, Search, Back } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../api/request'
import { useRegionStore } from '../stores/regions'
import { downloadFile } from '../utils/download'

const route = useRoute()
const router = useRouter()
const regionStore = useRegionStore()

const taskId = Number(route.params.id)

const task = ref(null)
const taskLoading = ref(false)
const items = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summary = ref({ speaker_count: 0, recording_total: 0, approved_total: 0, valid_duration_ms: 0 })
const keyword = ref('')
const teamCode = ref('')
const exporting = ref(false)

function regionName(code) {
  return regionStore.nameOf(code)
}

function statusLabel(s) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s
}
function statusTag(s) {
  return { draft: 'info', published: 'success', closed: 'danger' }[s] || 'info'
}

function fmtTime(iso) {
  return iso ? String(iso).slice(0, 16).replace('T', ' ') : '-'
}

function pad(n) {
  return String(n).padStart(2, '0')
}
function fmtDeadline(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '-'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtDuration(ms) {
  if (ms == null) return '-'
  const s = ms / 1000
  if (s >= 3600) return `${(s / 3600).toFixed(1)} 小时`
  if (s >= 60) return `${Math.floor(s / 60)}分${Math.round(s % 60)}秒`
  return `${s.toFixed(1)} 秒`
}

function pct(rate) {
  if (rate == null) return '-'
  return `${(rate * 100).toFixed(1)}%`
}

async function loadTask() {
  taskLoading.value = true
  try {
    task.value = await request.get(`/tasks/${taskId}`)
  } catch (e) {
    ElMessage.error('任务加载失败')
    router.push('/tasks')
  } finally {
    taskLoading.value = false
  }
}

async function loadContributors() {
  loading.value = true
  try {
    const data = await request.get(`/tasks/${taskId}/contributors`, {
      params: {
        page: page.value,
        page_size: pageSize.value,
        keyword: keyword.value || undefined,
        team_code: teamCode.value || undefined
      }
    })
    items.value = data.items
    total.value = data.total
    summary.value = data.summary || summary.value
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  keyword.value = ''
  teamCode.value = ''
  page.value = 1
  loadContributors()
}

async function exportTask() {
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (teamCode.value) params.set('team_code', teamCode.value)
  const qs = params.toString()
  await downloadFile(
    qs ? `/api/tasks/${taskId}/export?${qs}` : `/api/tasks/${taskId}/export`,
    `task_${taskId}_${Date.now()}.csv`,
    exporting
  )
}

onMounted(() => {
  loadTask()
  loadContributors()
})
</script>

<style scoped>
.task-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.detail-top {
  display: flex;
  align-items: center;
}
.task-card .task-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.task-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.title-text {
  font-size: 18px;
  font-weight: 600;
}
.task-summary {
  display: flex;
  gap: 16px;
}
.chip {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.chip b {
  color: var(--el-color-primary);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.total {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-left: 4px;
}
.pager {
  justify-content: flex-end;
  margin-top: 8px;
}
.muted {
  color: var(--el-text-color-placeholder);
}
</style>

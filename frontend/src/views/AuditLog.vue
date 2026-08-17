<template>
  <div>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- ===== 日志 ===== -->
      <el-tab-pane label="日志" name="log">
        <!-- 筛选栏 -->
        <el-card shadow="never" style="margin-bottom: 12px">
          <div class="filter-bar">
            <el-select v-model="filterAction" placeholder="全部操作" clearable style="width: 180px">
              <el-option v-for="a in actionOptions" :key="a" :label="a" :value="a" />
            </el-select>
            <el-input
              v-model="filterAdmin"
              placeholder="搜索管理员"
              clearable
              style="width: 160px"
              @keyup.enter="page = 1; load()"
            />
            <el-date-picker
              v-model="filterRange"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              style="width: 260px"
            />
            <el-button type="primary" :icon="Search" @click="load">查询</el-button>
            <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
            <span class="total">共 {{ total }} 条</span>
          </div>
        </el-card>

        <!-- 审计日志表格 -->
        <el-card shadow="never">
          <el-table :data="items" v-loading="loading" border stripe>
            <el-table-column label="时间" width="150">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column prop="admin_name" label="管理员" width="120" show-overflow-tooltip />
            <el-table-column prop="action" label="操作" width="140">
              <template #default="{ row }">
                <el-tag :type="actionMeta(row.action)?.type || 'info'" size="small">
                  {{ row.action }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="目标" width="120">
              <template #default="{ row }">
                <span v-if="row.target_type">{{ targetLabel(row.target_type) }}<span v-if="row.target_id"> #{{ row.target_id }}</span></span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
            <el-table-column prop="ip" label="IP" width="130" show-overflow-tooltip>
              <template #default="{ row }">{{ row.ip || '-' }}</template>
            </el-table-column>
            <el-table-column type="expand" width="40">
              <template #default="{ row }">
                <div v-if="row.detail && row.detail.length" class="detail-box">
                  <pre class="detail-json">{{ JSON.stringify(row.detail, null, 2) }}</pre>
                </div>
                <span v-else class="detail-empty">无额外信息</span>
              </template>
            </el-table-column>
          </el-table>

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
      </el-tab-pane>

      <!-- ===== 审核工作量报表（后台完善 9） ===== -->
      <el-tab-pane label="工作量" name="workload">
        <el-card shadow="never" style="margin-bottom: 12px">
          <div class="filter-bar">
            <el-select v-model="workloadDays" style="width: 140px" @change="loadWorkload">
              <el-option label="今日" :value="1" />
              <el-option label="近 7 天" :value="7" />
              <el-option label="近 30 天" :value="30" />
            </el-select>
            <el-button type="primary" :icon="Search" :loading="workloadLoading" @click="loadWorkload">刷新</el-button>
            <span class="total">共 {{ workload.total }} 位审核员有记录</span>
          </div>
          <div class="workload-summary">
            <span>审核员 <b>{{ workloadSummary.reviewers }}</b> 位</span>
            <span>窗口内审核 <b>{{ workloadSummary.totalReviewed }}</b> 条</span>
            <span>总通过率 <b>{{ workloadSummary.rate.toFixed(1) }}%</b></span>
            <span class="muted">按录音审核结果统计（重置为待审 / 删除不计入）</span>
          </div>
        </el-card>

        <el-card shadow="never">
          <el-table :data="workload.items" v-loading="workloadLoading" border stripe empty-text="该窗口暂无审核记录">
            <el-table-column prop="admin_name" label="审核员" min-width="140" show-overflow-tooltip />
            <el-table-column prop="total" label="审核条数" width="100" sortable />
            <el-table-column prop="approved" label="通过" width="90">
              <template #default="{ row }"><span class="num-ok">{{ row.approved }}</span></template>
            </el-table-column>
            <el-table-column prop="rejected" label="驳回" width="90">
              <template #default="{ row }"><span class="num-bad">{{ row.rejected }}</span></template>
            </el-table-column>
            <el-table-column label="通过率" width="100">
              <template #default="{ row }">
                <el-tag :type="rateTag(row.approval_rate)" size="small">{{ (row.approval_rate * 100).toFixed(0) }}%</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="驳回原因" min-width="240">
              <template #default="{ row }">
                <template v-if="row.reasons && row.reasons.length">
                  <el-tag
                    v-for="r in row.reasons"
                    :key="r.key"
                    size="small"
                    type="danger"
                    effect="plain"
                    style="margin-right: 4px"
                  >
                    {{ r.label }}×{{ r.count }}
                  </el-tag>
                </template>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Search, RefreshLeft } from '@element-plus/icons-vue'
import request from '../api/request'

const actionOptions = [
  '创建管理员', '修改管理员', '删除管理员',
  '删除发音人', '合并发音人',
  '删除词条', '合并词条',
  '删除任务', '发布任务', '关闭任务', '重新打开任务', '解绑领取',
  '审核通过', '审核驳回', '批量审核通过', '批量审核驳回', '重置为待审', '删除录音',
  '删除团队码',
  '导入词表'
]

const targetMeta = {
  admin: '管理员', speaker: '发音人', word: '词条', task: '任务',
  recording: '录音', team_code: '团队码', import: '词表导入'
}

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterAction = ref('')
const filterAdmin = ref('')
const filterRange = ref(null)

// —— 审核工作量报表（后台完善 9）——
const activeTab = ref('log')
const workloadDays = ref(7)
const workloadLoading = ref(false)
const workload = ref({ items: [], total: 0, days: 7 })

const workloadSummary = computed(() => {
  const rows = workload.value.items || []
  const totalReviewed = rows.reduce((s, r) => s + (r.total || 0), 0)
  const totalApproved = rows.reduce((s, r) => s + (r.approved || 0), 0)
  const rate = totalReviewed ? (totalApproved / totalReviewed) * 100 : 0
  return { reviewers: workload.value.total || 0, totalReviewed, rate }
})

function rateTag(rate) {
  if (rate >= 0.8) return 'success'
  if (rate >= 0.5) return 'warning'
  return 'danger'
}

function actionMeta(action) {
  if (action.includes('审核') || action.includes('删除')) return { type: 'danger' }
  if (action.includes('合并') || action.includes('解绑')) return { type: 'warning' }
  return { type: 'info' }
}

function targetLabel(t) {
  return targetMeta[t] || t
}

function fmtTime(iso) {
  if (!iso) return '-'
  return iso.slice(0, 16).replace('T', ' ')
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filterAction.value) params.action = filterAction.value
    if (filterAdmin.value) params.keyword = filterAdmin.value
    if (filterRange.value && filterRange.value.length === 2) {
      params.start = filterRange.value[0].toISOString()
      params.end = filterRange.value[1].toISOString()
    }
    const data = await request.get('/audit-logs', { params })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function reset() {
  filterAction.value = ''
  filterAdmin.value = ''
  filterRange.value = null
  page.value = 1
  load()
}

async function loadWorkload() {
  workloadLoading.value = true
  try {
    const data = await request.get('/audit-logs/workload', { params: { days: workloadDays.value } })
    workload.value = data
  } finally {
    workloadLoading.value = false
  }
}

function onTabChange(name) {
  // 切到工作量 Tab 首次加载；日志 Tab 保持默认加载
  if (name === 'workload' && !workload.value.items.length) loadWorkload()
}

onMounted(load)
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.total {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.detail-box {
  padding: 10px 14px;
}
.detail-json {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
  border-radius: 4px;
  padding: 8px 10px;
}
.detail-empty {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  padding: 10px 14px;
}
.workload-summary {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.workload-summary b {
  font-size: 15px;
  color: var(--el-text-color-primary);
}
.workload-summary .muted {
  margin-left: auto;
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.num-ok {
  color: #67c23a;
  font-weight: 600;
}
.num-bad {
  color: #f56c6c;
  font-weight: 600;
}
</style>

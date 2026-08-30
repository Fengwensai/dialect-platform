<template>
  <div class="dashboard-page">
    <!-- ===== 概览卡片 ===== -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="card-head">
        <b>平台概览</b>
        <el-button size="small" :icon="Refresh" :loading="summaryLoading" @click="refreshOverview">刷新</el-button>
      </div>
      <div v-loading="summaryLoading" class="stats-row">
        <div class="stat-box"><div class="stat-num">{{ summary?.speaker_total ?? '-' }}</div><div class="stat-label">发音人总数</div></div>
        <div class="stat-box"><div class="stat-num">{{ summary?.recording_total ?? '-' }}</div><div class="stat-label">录音总数</div></div>
        <div class="stat-box warn"><div class="stat-num">{{ summary?.pending ?? '-' }}</div><div class="stat-label">待审核</div></div>
        <div class="stat-box ok"><div class="stat-num">{{ summary?.approved ?? '-' }}</div><div class="stat-label">已通过</div></div>
        <div class="stat-box bad"><div class="stat-num">{{ summary?.rejected ?? '-' }}</div><div class="stat-label">已驳回</div></div>
        <div class="stat-box"><div class="stat-num">{{ fmtTotalDur(summary?.total_duration_ms) }}</div><div class="stat-label">总时长</div></div>
        <div class="stat-box ok"><div class="stat-num">{{ fmtTotalDur(summary?.approved_duration_ms) }}</div><div class="stat-label">有效时长</div></div>
        <div class="stat-box"><div class="stat-num">{{ pct(summary?.approval_rate) }}</div><div class="stat-label">通过率</div></div>
      </div>
      <div class="sub-line">
        <span>活跃任务 <b>{{ summary?.active_task_total ?? '-' }}</b></span>
        <span>团队数 <b>{{ summary?.team_total ?? '-' }}</b></span>
        <span>已录词条 <b>{{ summary?.distinct_word_total ?? '-' }}</b></span>
      </div>

      <!-- 近 N 天趋势（数字卡片） -->
      <div class="trend-block">
        <div class="trend-head">
          <span class="trend-title">录音趋势</span>
          <el-radio-group v-model="trendDays" size="small" @change="loadTrends">
            <el-radio-button :value="7">近 7 天</el-radio-button>
            <el-radio-button :value="30">近 30 天</el-radio-button>
          </el-radio-group>
        </div>
        <div v-loading="trendLoading" class="stats-row">
          <div class="stat-box"><div class="stat-num">{{ trend?.new_recordings ?? '-' }}</div><div class="stat-label">新增录音</div></div>
          <div class="stat-box ok"><div class="stat-num">{{ trend?.approved ?? '-' }}</div><div class="stat-label">已通过</div></div>
          <div class="stat-box bad"><div class="stat-num">{{ trend?.rejected ?? '-' }}</div><div class="stat-label">已驳回</div></div>
          <div class="stat-box"><div class="stat-num">{{ pct(trend?.approval_rate) }}</div><div class="stat-label">通过率</div></div>
        </div>
      </div>

      <!-- 区域分布 -->
      <div v-if="summary?.region_breakdown?.length" class="region-block">
        <span class="region-title">{{ auth.isSuper ? '省份分布' : '本省市级分布' }}</span>
        <el-table :data="summary.region_breakdown" border size="small" class="region-table">
          <el-table-column prop="name" label="地区" min-width="140" />
          <el-table-column prop="speaker_total" label="发音人数" width="110" />
          <el-table-column prop="recording_total" label="录音数" width="110" />
        </el-table>
      </div>
    </el-card>

    <!-- ===== 业务健康 ===== -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="card-head">
        <b>业务健康</b>
        <el-button size="small" :icon="Refresh" :loading="healthLoading" @click="loadHealth">刷新</el-button>
      </div>
      <div v-loading="healthLoading" class="stats-row">
        <div class="stat-box warn" :class="{ bad: health?.backlog_level === 'high' }">
          <div class="stat-num">{{ health?.pending ?? '-' }}</div>
          <div class="stat-label">待审核积压{{ health?.backlog_level === 'high' ? '（积压）' : '' }}</div>
        </div>
        <div
          class="stat-box warn"
          :class="{ bad: (health?.expired_tasks ?? 0) > 0 }"
          style="cursor: pointer"
          title="到期任务列表"
          @click="$router.push('/tasks')"
        >
          <div class="stat-num">{{ health?.expired_tasks ?? '-' }}</div>
          <div class="stat-label">到期任务{{ (health?.expired_tasks ?? 0) > 0 ? '（催收）' : '' }}</div>
        </div>
        <div class="stat-box"><div class="stat-num">{{ health?.today_uploaded ?? '-' }}</div><div class="stat-label">今日上传</div></div>
        <div class="stat-box ok"><div class="stat-num">{{ health?.today_approved ?? '-' }}</div><div class="stat-label">今日通过</div></div>
        <div class="stat-box bad"><div class="stat-num">{{ health?.today_rejected ?? '-' }}</div><div class="stat-label">今日驳回</div></div>
        <div class="stat-box" :class="{ bad: health?.disk_level === 'warn' }">
          <div class="stat-num">{{ health?.disk_free_gb ?? '-' }}<span class="stat-unit">GB</span></div>
          <div class="stat-label">磁盘剩余（已用 {{ health?.disk_used_pct ?? '-' }}%）</div>
        </div>
        <div class="stat-box"><div class="stat-num">{{ storageLabel }}</div><div class="stat-label">存储方式</div></div>
      </div>
    </el-card>

    <!-- ===== 词条采集难度 ===== -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-head">
          <b>词条采集难度</b>
          <el-select v-model="wordSort" style="width: 150px" @change="wordPage = 1; loadWordDifficulty()">
            <el-option label="按驳回数" value="reject" />
            <el-option label="按通过率" value="approval" />
            <el-option label="按录音数" value="recording" />
          </el-select>
        </div>
      </template>
      <el-table :data="wordItems" v-loading="wordLoading" border stripe>
        <el-table-column prop="code" label="编号" width="100" show-overflow-tooltip />
        <el-table-column prop="content" label="词条" min-width="140" show-overflow-tooltip />
        <el-table-column prop="dialect_point" label="方言点" width="150" show-overflow-tooltip />
        <el-table-column prop="recording_total" label="录音" width="70" />
        <el-table-column label="待审" width="70">
          <template #default="{ row }"><span class="num-warn">{{ row.pending }}</span></template>
        </el-table-column>
        <el-table-column label="通过" width="70">
          <template #default="{ row }"><span class="num-ok">{{ row.approved }}</span></template>
        </el-table-column>
        <el-table-column label="驳回" width="70">
          <template #default="{ row }"><span class="num-bad">{{ row.rejected }}</span></template>
        </el-table-column>
        <el-table-column label="通过率" width="90">
          <template #default="{ row }">{{ pct(row.approval_rate) }}</template>
        </el-table-column>
        <el-table-column label="驳回率" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.reject_rate" type="danger" size="small">{{ pct(row.reject_rate) }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pager"
        background
        layout="total, prev, pager, next"
        :total="wordTotal"
        :page-size="wordPageSize"
        :current-page="wordPage"
        @current-change="(p) => { wordPage = p; loadWordDifficulty() }"
      />
    </el-card>

    <!-- ===== 驳回原因分布 ===== -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header><b>驳回原因分布</b></template>
      <el-table :data="rejectReasons?.items || []" v-loading="rejectReasonsLoading" border stripe>
        <el-table-column label="原因" min-width="140">
          <template #default="{ row }">
            <el-tag :type="row.reason === 'unknown' ? 'info' : 'danger'" size="small">{{ row.label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="90">
          <template #default="{ row }"><span class="num-bad">{{ row.count }}</span></template>
        </el-table-column>
        <el-table-column label="占比" min-width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="rejectReasons?.total ? Math.round((row.count / rejectReasons.total) * 100) : 0"
              :stroke-width="14"
              :format="() => (rejectReasons?.total ? pct(row.count / rejectReasons.total) : '-')"
            />
          </template>
        </el-table-column>
      </el-table>
      <div v-if="rejectReasons?.total" class="rr-total">
        统计范围：{{ rejectReasons.total }} 条已驳回录音（省域管理员仅统计本省）；未勾选原因的计入「未标注」
      </div>
      <div v-else class="rr-total">暂无已驳回录音</div>
    </el-card>

    <!-- ===== 发音人数据表 ===== -->
    <el-card shadow="never">
      <template #header><b>发音人数据（{{ total }} 人）</b></template>
      <div class="filter-bar">
        <el-select v-model="filterProvince" placeholder="全部省份" clearable filterable style="width: 150px">
          <el-option v-for="p in provinceOptions" :key="p.code" :label="p.name" :value="p.code" />
        </el-select>
        <el-input v-model="keyword" placeholder="搜索昵称 / 设备ID / openid" clearable style="width: 220px" @keyup.enter="loadSpeakers" />
        <el-select v-model="filterGender" placeholder="全部性别" clearable style="width: 110px">
          <el-option label="男" value="male" />
          <el-option label="女" value="female" />
          <el-option label="其他" value="other" />
        </el-select>
        <el-select v-model="filterAgeBracket" placeholder="全部年龄段" clearable style="width: 130px">
          <el-option v-for="(label, code) in AGE_LABELS" :key="code" :label="label" :value="code" />
        </el-select>
        <el-input v-model="filterTeam" placeholder="团队码" clearable style="width: 130px" @keyup.enter="loadSpeakers" />
        <el-select v-model="sortBy" style="width: 130px">
          <el-option label="按ID正序" value="id" />
          <el-option label="按录音数" value="recording" />
          <el-option label="按通过数" value="approved" />
          <el-option label="按总时长" value="duration" />
          <el-option label="按最近活跃" value="last_active" />
          <el-option label="按建档时间" value="created" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="loadSpeakers">查询</el-button>
        <el-button :icon="RefreshLeft" @click="resetFilters">重置</el-button>
        <el-button type="success" :icon="Download" :loading="exporting" @click="exportDurations">导出时长</el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>

      <el-table :data="items" v-loading="loading" border stripe :row-class-name="rowClass">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="nickname" label="昵称" width="110" show-overflow-tooltip />
        <el-table-column prop="device_id" label="设备ID" width="150" show-overflow-tooltip />
        <el-table-column label="属地" width="150">
          <template #default="{ row }">
            <template v-if="row.province_code">
              {{ regionName(row.province_code) }}<template v-if="row.city_code">·{{ regionName(row.city_code) }}</template><template v-if="row.district_code">·{{ regionName(row.district_code) }}</template>
            </template>
            <el-tag v-else type="info" size="small">未绑定</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="团队码" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.team_code" type="warning" effect="plain" size="small">{{ row.team_code }}</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="性别" width="70">
          <template #default="{ row }">{{ genderText(row.gender) }}</template>
        </el-table-column>
        <el-table-column label="年龄段" width="80">
          <template #default="{ row }">{{ ageText(row.age_bracket) }}</template>
        </el-table-column>
        <el-table-column prop="recording_total" label="录音数" width="75" sortable />
        <el-table-column label="待审/通过/驳回" width="130">
          <template #default="{ row }">
            <span class="num-warn">{{ row.pending }}</span>
            <span class="sep">/</span>
            <span class="num-ok">{{ row.approved }}</span>
            <span class="sep">/</span>
            <span class="num-bad">{{ row.rejected }}</span>
          </template>
        </el-table-column>
        <el-table-column label="总时长" width="90">
          <template #default="{ row }">{{ fmtTotalDur(row.total_duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="通过率" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.quality_warned" type="warning" size="small">低质预警</el-tag>
            <span :class="row.quality_warned ? 'num-warn' : ''">{{ pct(row.approval_rate) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="task_count" label="任务数" width="70" />
        <el-table-column prop="word_count" label="词条数" width="70" />
        <el-table-column label="最近活跃" width="160">
          <template #default="{ row }">{{ row.last_active_at?.slice(0, 16) || '-' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="建档时间" width="150">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
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
        @current-change="(p) => { page = p; loadSpeakers() }"
        @size-change="(s) => { pageSize = s; page = 1; loadSpeakers() }"
      />
    </el-card>

    <!-- ===== 详情对话框 ===== -->
    <el-dialog
      v-model="detailVisible"
      :title="detailTitle"
      width="920px"
      top="4vh"
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
            <el-tag v-if="detailSpeaker.team_code" type="warning" effect="plain" size="small">{{ detailSpeaker.team_code }}</el-tag>
          </div>

          <div v-if="detailStats" class="stats-row">
            <div class="stat-box"><div class="stat-num">{{ detailStats.total }}</div><div class="stat-label">总录音</div></div>
            <div class="stat-box warn"><div class="stat-num">{{ detailStats.pending }}</div><div class="stat-label">待审核</div></div>
            <div class="stat-box ok"><div class="stat-num">{{ detailStats.approved }}</div><div class="stat-label">已通过</div></div>
            <div class="stat-box bad"><div class="stat-num">{{ detailStats.rejected }}</div><div class="stat-label">已驳回</div></div>
            <div class="stat-box"><div class="stat-num">{{ fmtTotalDur(detailStats.total_duration_ms) }}</div><div class="stat-label">总时长</div></div>
            <div class="stat-box ok"><div class="stat-num">{{ fmtTotalDur(detailStats.approved_duration_ms) }}</div><div class="stat-label">有效时长</div></div>
            <div class="stat-box bad"><div class="stat-num">{{ fmtTotalDur(detailStats.rejected_duration_ms) }}</div><div class="stat-label">无效时长</div></div>
          </div>

          <div v-if="detailStats && detailStats.tasks.length" class="task-row">
            <span class="task-label">任务分布：</span>
            <el-tag v-for="t in detailStats.tasks" :key="t.task_id" size="small" effect="plain" class="task-chip">
              {{ t.task_name }} × {{ t.count }}
            </el-tag>
          </div>

          <el-tabs v-model="activeTab" style="margin-top: 6px">
            <!-- 录音明细 -->
            <el-tab-pane label="录音明细" name="recordings">
              <div class="filter-bar" style="margin: 0 0 8px">
                <el-select v-model="detailTaskId" placeholder="全部任务" clearable filterable style="width: 250px">
                  <el-option v-for="t in detailStats ? detailStats.tasks : []" :key="t.task_id" :label="t.task_name" :value="t.task_id" />
                </el-select>
                <el-select v-model="detailStatus" placeholder="状态" clearable style="width: 120px">
                  <el-option label="待审核" value="pending" />
                  <el-option label="已通过" value="approved" />
                  <el-option label="已驳回" value="rejected" />
                </el-select>
                <el-button type="primary" size="small" @click="detailPage = 1; loadRecordings()">查询</el-button>
                <el-button size="small" @click="resetDetail">重置</el-button>
                <el-button type="success" size="small" :loading="detailExporting" @click="exportDetail">导出</el-button>
                <span class="total">共 {{ detailTotal }} 条</span>
              </div>
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
                <el-table-column label="音频" width="210">
                  <template #default="{ row }">
                    <audio controls :src="row.audio_url" preload="none" class="player-sm" />
                  </template>
                </el-table-column>
                <el-table-column label="时长" width="70">
                  <template #default="{ row }">{{ fmtDuration(row.audio_duration) }}</template>
                </el-table-column>
                <el-table-column prop="review_note" label="审核备注" min-width="100" show-overflow-tooltip>
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
                @current-change="(p) => { detailPage = p; loadRecordings() }"
              />
            </el-tab-pane>

            <!-- 领取记录 -->
            <el-tab-pane :label="`领取记录（${claims.length}）`" name="claims">
              <div v-loading="claimsLoading">
                <el-table v-if="claims.length" :data="claims" border stripe size="small">
                  <el-table-column label="词条" min-width="160">
                    <template #default="{ row }">
                      <span class="word">{{ row.word_content }}</span>
                      <span v-if="row.word_code" class="code">{{ row.word_code }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="task_name" label="任务" min-width="140" show-overflow-tooltip />
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <el-tag v-if="row.recorded" type="success" size="small">已录</el-tag>
                      <el-tag v-else type="info" size="small">未录</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="领取时间" width="160">
                    <template #default="{ row }">{{ row.claimed_at?.slice(0, 16) }}</template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="暂无领取记录" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Search, RefreshLeft, Download, Refresh } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'
import { useRegionStore } from '../stores/regions'
import { downloadFile } from '../utils/download'

const GENDER_LABELS = { male: '男', female: '女', other: '其他' }
const AGE_LABELS = { under18: '<18', age18_30: '18-30', age31_45: '31-45', age46_60: '46-60', over60: '>60' }

const auth = useAuthStore()
const regionStore = useRegionStore()

// —— 概览 ——
const summary = ref(null)
const summaryLoading = ref(false)
const health = ref(null) // 业务健康（后台完善 8）
const healthLoading = ref(false)

// —— 趋势（近 N 天数字卡片）——
const trendDays = ref(7)
const trend = ref(null)
const trendLoading = ref(false)

// —— 词条采集难度 ——
const wordItems = ref([])
const wordTotal = ref(0)
const wordPage = ref(1)
const wordPageSize = ref(20)
const wordSort = ref('reject')
const wordLoading = ref(false)

// —— 驳回原因分布（后台完善 2）——
const rejectReasons = ref(null)
const rejectReasonsLoading = ref(false)

// —— 发音人表 ——
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const filterProvince = ref('')
const filterGender = ref('')
const filterAgeBracket = ref('')
const filterTeam = ref('')
const sortBy = ref('id')
const loading = ref(false)
const exporting = ref(false)

// —— 详情 ——
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
const detailExporting = ref(false)
const activeTab = ref('recordings')
const claims = ref([])
const claimsLoading = ref(false)

const statusMeta = {
  pending: { type: 'warning', label: '待审核' },
  approved: { type: 'success', label: '已通过' },
  rejected: { type: 'danger', label: '已驳回' }
}

const detailTitle = computed(() =>
  detailSpeaker.value
    ? `发音人详情 — ${detailSpeaker.value.nickname || ('#' + detailSpeaker.value.id)}`
    : '发音人详情'
)

const provinceOptions = computed(() => {
  if (auth.isSuper) return regionStore.tree
  const locked = auth.provinceCode
  return locked ? (regionStore.tree || []).filter((p) => p.code === locked) : []
})

function regionName(code) {
  return regionStore.nameOf(code)
}
function genderText(code) {
  return code ? (GENDER_LABELS[code] || code) : '-'
}
function ageText(code) {
  return code ? (AGE_LABELS[code] || code) : '-'
}
function pct(v) {
  if (v === null || v === undefined) return '-'
  return (v * 100).toFixed(1) + '%'
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

async function loadSummary() {
  summaryLoading.value = true
  try {
    summary.value = await request.get('/dashboard/summary')
  } finally {
    summaryLoading.value = false
  }
}

function refreshOverview() {
  loadSummary()
  loadTrends()
}

async function loadTrends() {
  trendLoading.value = true
  try {
    trend.value = await request.get('/dashboard/trends', { params: { days: trendDays.value } })
  } finally {
    trendLoading.value = false
  }
}

async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = await request.get('/dashboard/health')
  } finally {
    healthLoading.value = false
  }
}

const storageLabel = computed(() =>
  health.value?.storage === 'cos' ? '腾讯云 COS' : '本地磁盘'
)

async function loadWordDifficulty() {
  wordLoading.value = true
  try {
    const data = await request.get('/dashboard/words', {
      params: { page: wordPage.value, page_size: wordPageSize.value, sort_by: wordSort.value }
    })
    wordItems.value = data.items
    wordTotal.value = data.total
  } finally {
    wordLoading.value = false
  }
}

async function loadRejectReasons() {
  rejectReasonsLoading.value = true
  try {
    rejectReasons.value = await request.get('/dashboard/rejection-reasons')
  } finally {
    rejectReasonsLoading.value = false
  }
}

async function loadSpeakers() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort_by: sortBy.value,
      keyword: keyword.value || undefined,
      province_code: filterProvince.value || undefined,
      gender: filterGender.value || undefined,
      age_bracket: filterAgeBracket.value || undefined,
      team_code: filterTeam.value || undefined
    }
    const data = await request.get('/dashboard/speakers', { params })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

// 质量预警（后台完善 3）：低质预警发音人行整行标黄提醒
function rowClass({ row }) {
  return row.quality_warned ? 'row-warn' : ''
}

function resetFilters() {
  keyword.value = ''
  filterProvince.value = ''
  filterGender.value = ''
  filterAgeBracket.value = ''
  filterTeam.value = ''
  sortBy.value = 'id'
  page.value = 1
  loadSpeakers()
}

async function openDetail(row) {
  detailSpeaker.value = row
  detailPage.value = 1
  detailTaskId.value = null
  detailStatus.value = ''
  activeTab.value = 'recordings'
  detailVisible.value = true
  await Promise.all([loadRecordings(), loadClaims()])
}

async function loadRecordings() {
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

async function loadClaims() {
  if (!detailSpeaker.value) return
  claimsLoading.value = true
  try {
    claims.value = await request.get(`/dashboard/speakers/${detailSpeaker.value.id}/claims`)
  } finally {
    claimsLoading.value = false
  }
}

function resetDetail() {
  detailTaskId.value = null
  detailStatus.value = ''
  detailPage.value = 1
  loadRecordings()
}

/** 导出发音人时长汇总 CSV（遵循当前筛选） */
async function exportDurations() {
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (filterProvince.value) params.set('province_code', filterProvince.value)
  if (filterGender.value) params.set('gender', filterGender.value)
  if (filterAgeBracket.value) params.set('age_bracket', filterAgeBracket.value)
  if (filterTeam.value) params.set('team_code', filterTeam.value)
  const qs = params.toString()
  await downloadFile(
    qs ? `/api/speakers/export?${qs}` : '/api/speakers/export',
    `speakers_duration_${Date.now()}.csv`,
    exporting
  )
}

/** 导出发音人录音明细 CSV */
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

onMounted(async () => {
  await regionStore.ensureLoaded()
  loadSummary()
  loadTrends()
  loadHealth()
  loadWordDifficulty()
  loadRejectReasons()
  loadSpeakers()
})
</script>

<!-- 质量预警标黄：给 el-table 内部 td 上色必须非 scoped（照 ExcelImport.vue 先例） -->
<style>
.dashboard-page .el-table .row-warn td {
  background-color: rgba(230, 162, 60, 0.12);
}
</style>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.rr-total {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.stats-row {
  display: flex;
  gap: 10px;
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
.stat-unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 2px;
}
.stat-label {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.sub-line {
  display: flex;
  gap: 22px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.sub-line b {
  color: var(--el-text-color-primary);
  margin-left: 2px;
}
.trend-block {
  margin-top: 14px;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 12px;
}
.trend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.trend-title {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.region-block {
  margin-top: 14px;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 12px;
}
.region-title {
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: inline-block;
  margin-bottom: 8px;
}
.region-table {
  max-width: 380px;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.total {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.muted {
  color: var(--el-text-color-placeholder);
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.num-warn { color: #e6a23c; font-weight: 600; }
.num-ok { color: #67c23a; font-weight: 600; }
.num-bad { color: #f56c6c; font-weight: 600; }
.sep { color: var(--el-text-color-placeholder); margin: 0 3px; }
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
.task-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
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
  width: 200px;
  height: 32px;
  vertical-align: middle;
}
</style>

<template>
  <div>
    <!-- 创建任务 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header><b>创建任务包</b></template>
      <el-form :model="form" label-width="100px">
        <el-row :gutter="20">
          <el-col :xs="24" :span="8">
            <el-form-item label="任务名称" required>
              <el-input v-model="form.name" placeholder="如：河北省核心词任务" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :span="8">
            <el-form-item label="关联团队">
              <el-select
                v-model="selectedTeamCode"
                filterable
                clearable
                placeholder="选团队后地区自动带出"
                style="width: 100%"
                @change="onTeamChange"
              >
                <el-option v-for="t in teams" :key="t.code" :label="`${t.code} · ${t.name}`" :value="t.code">
                  <span>{{ t.code }} · {{ t.name }}</span>
                  <span class="opt-code">{{ regionName(t.province_code) }}-{{ regionName(t.city_code) }}</span>
                </el-option>
              </el-select>
              <div v-if="selectedTeamInfo" class="tip">投放区划由团队码自动带出：{{ selectedTeamInfo }}</div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :span="8">
            <el-form-item label="投放区划" required>
              <el-cascader
                v-model="taskRegion"
                :options="regionOptions"
                :props="cascaderProps"
                placeholder="省 / 市 / 区"
                filterable
                style="width: 100%"
                :disabled="regionLocked"
                @change="onTaskRegionChange"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :xs="24" :span="8">
            <el-form-item label="必录音频数">
              <el-input-number v-model="form.required_audio_count" :min="1" :max="5000" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :span="8">
            <el-form-item label="每人领取上限">
              <el-input-number v-model="form.claim_limit" :min="1" :max="500" />
              <div class="tip">领取制：每人同时最多领取的词条数</div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :span="8">
            <el-form-item label="截止时间">
              <el-date-picker
                v-model="form.deadline_at"
                type="datetime"
                placeholder="选填；到点任务标「已截止」"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
              />
              <div class="tip">发布后过截止时间 → 列表/看板标「已截止」，可一键清理到期任务关闭</div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :xs="24" :span="24">
            <el-form-item label="说明">
              <el-input v-model="form.description" placeholder="任务说明（选填）" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="auth.isSuper">
          <el-col :span="24">
            <el-form-item label="演示任务">
              <el-checkbox v-model="form.is_demo">
                演示任务（审核/体验用：未绑定团队的用户也能看、能录；请用「创建并发布」，审核后清理）
              </el-checkbox>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <!-- 词条选择 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <b>选择词条</b>
          <span class="selected-info">
            <template v-if="selectedWords.size">
              已选 <b>{{ selectedWords.size }}</b> 条
              <el-button link type="primary" @click="selectedVisible = true">查看清单</el-button>
            </template>
            <span v-else>未选词条</span>
          </span>
        </div>
      </template>

      <div class="filter-bar">
        <div class="filter-group">
          <el-cascader
            v-model="wordFilterRegion"
            :options="regionOptions"
            :props="cascaderProps"
            placeholder="按区划筛选词条"
            clearable
            filterable
            style="width: 300px"
          />
          <el-input v-model="wordKeyword" placeholder="搜索词条" clearable style="width: 200px" @keyup.enter="loadWords" />
          <el-button type="primary" :icon="Search" @click="loadWords">筛选</el-button>
        </div>
        <div class="filter-group filter-group--ops">
          <el-button :disabled="!words.length" @click="selectPage">全选当前页</el-button>
          <el-button :loading="selectingAll" @click="selectAllFiltered">跨页全选</el-button>
          <el-button @click="clearSelection">清空已选</el-button>
        </div>
      </div>
      <div v-if="occupiedCount" class="occupied-hint">
        当前页有 <b>{{ occupiedCount }}</b> 条词条已占用，不可勾选
      </div>

      <el-table ref="wordsTable" :data="words" row-key="id" v-loading="wordsLoading" border size="small" max-height="360" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="46" :reserve-selection="true" :selectable="(row) => !row.occupied" />
        <el-table-column prop="code" label="编号" width="100" show-overflow-tooltip />
        <el-table-column prop="dialect_point" label="方言点" width="150" show-overflow-tooltip />
        <el-table-column label="词条内容" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.content }}
            <el-tag v-if="row.occupied" size="small" type="info" style="margin-left: 4px">已占用</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="example_sentence" label="例句" min-width="180" show-overflow-tooltip />
        <template #empty>
          <div class="table-empty">
            <p>当前筛选下暂无词条</p>
            <p class="muted">可调整区划或搜索关键词，或先到「词条库」录入词条</p>
          </div>
        </template>
      </el-table>
      <el-pagination
        class="pager"
        small
        background
        layout="total, prev, pager, next, sizes"
        :total="wordTotal"
        :page-size="wordPageSize"
        :current-page="wordPage"
        :page-sizes="[20, 50, 100, 200]"
        @current-change="(p) => { wordPage = p; loadWords() }"
        @size-change="(s) => { wordPageSize = s; wordPage = 1; loadWords() }"
      />
      <div class="actions">
        <el-button type="primary" :loading="creating" :disabled="!selectedWords.size" @click="createTask(false)">保存草稿</el-button>
        <el-button type="success" :loading="creating" :disabled="!selectedWords.size" @click="createTask(true)">创建并发布</el-button>
      </div>
    </el-card>

    <!-- 已选词条清单（抽屉，按方言点分组） -->
    <el-drawer v-model="selectedVisible" title="已选词条清单" size="500px">
      <div class="drawer-bar">
        <span class="selected-info">已选 <b>{{ selectedWords.size }}</b> 条 · {{ selectedByPoint.length }} 个方言点</span>
        <el-button size="small" type="danger" plain :disabled="!selectedWords.size" @click="clearSelection">一键清空</el-button>
      </div>
      <div v-if="!selectedWords.size" class="selected-empty">还没有已选词条</div>
      <div v-for="[point, items] in selectedByPoint" :key="point" class="point-group">
        <div class="point-header">
          <span>{{ point }}</span>
          <span class="selected-info">{{ items.length }} 条</span>
        </div>
        <el-table :data="items" border size="small" max-height="240">
          <el-table-column prop="code" label="编号" width="100" show-overflow-tooltip />
          <el-table-column prop="content" label="词条内容" min-width="170" show-overflow-tooltip />
          <el-table-column label="操作" width="70" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeSelectedWord(row.id)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>

    <!-- 任务列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <b>已创建任务（{{ taskTotal }}）</b>
          <el-button
            size="small"
            type="warning"
            plain
            :loading="cleaning"
            @click="cleanupExpired"
          >
            清理到期任务
          </el-button>
        </div>
      </template>
      <el-table :data="tasks" v-loading="tasksLoading" border>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="任务名称" min-width="180">
          <template #default="{ row }">
            <el-tag v-if="row.is_demo" size="small" type="warning" style="margin-right: 4px">演示</el-tag>
            <span>{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="投放区划" width="150">
          <template #default="{ row }">{{ regionName(row.province_code) }}{{ row.city_code ? '-' + regionName(row.city_code) : '' }}{{ row.district_code ? '-' + regionName(row.district_code) : '' }}</template>
        </el-table-column>
        <el-table-column label="关联团队" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.team_code" size="small" type="warning">{{ row.team_code }}</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="word_count" label="词条数" width="80" />
        <el-table-column prop="required_audio_count" label="必录数" width="80" />
        <el-table-column prop="claim_limit" label="领取上限" width="90" />
        <el-table-column label="任务进度" width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="taskPct(row)"
              :stroke-width="10"
              :format="() => `${row.recorded_count || 0}/${row.word_count || 0}`"
            />
            <div class="task-progress-meta">
              <span class="muted">通过 {{ row.approved_count || 0 }}</span>
              <el-tag :type="completionTag(row.completion_status)" size="small">{{ completionLabel(row.completion_status) }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="截止时间" width="185">
          <template #default="{ row }">
            <template v-if="row.deadline_at">
              <span :class="{ 'deadline-expired': row.completion_status === 'expired' }">
                {{ fmtDeadline(row.deadline_at) }}
              </span>
              <span class="muted" :class="{ 'deadline-expired': row.completion_status === 'expired' }">
                · {{ deadlineRemain(row.deadline_at) }}
              </span>
            </template>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'draft'" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.status === 'draft'" link type="success" @click="publish(row)">发布</el-button>
            <el-button v-if="row.status === 'published'" link type="warning" @click="closeTask(row)">关闭</el-button>
            <el-button v-if="row.status === 'closed'" link type="success" @click="reopenTask(row)">打开</el-button>
            <el-button link type="primary" @click="openWords(row)">词条</el-button>
            <el-button link type="warning" @click="openClaims(row)">领取</el-button>
            <el-button link type="danger" @click="removeTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pager"
        background
        layout="total, prev, pager, next, sizes"
        :total="taskTotal"
        :page-size="taskPageSize"
        :current-page="taskPage"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="(p) => { taskPage = p; loadTasks() }"
        @size-change="(s) => { taskPageSize = s; taskPage = 1; loadTasks() }"
      />
    </el-card>

    <!-- 编辑草稿任务 -->
    <el-dialog v-model="editVisible" title="编辑草稿任务" width="640px" :close-on-click-modal="false">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="任务名称" required>
          <el-input v-model="editForm.name" placeholder="如：河北省核心词任务" />
        </el-form-item>
        <el-form-item label="关联团队">
          <el-select
            v-model="editForm.team_code"
            filterable
            clearable
            placeholder="选择团队后地区自动带出（解绑保留当前地区）"
            style="width: 100%"
          >
            <el-option v-for="t in teams" :key="t.code" :label="`${t.code} · ${t.name}`" :value="t.code">
              <span>{{ t.code }} · {{ t.name }}</span>
              <span class="opt-code">{{ regionName(t.province_code) }}-{{ regionName(t.city_code) }}</span>
            </el-option>
          </el-select>
          <div v-if="editTeamRegion" class="tip">投放区划（改绑后）：{{ editTeamRegion }}</div>
        </el-form-item>
        <el-form-item label="必录音频数">
          <el-input-number v-model="editForm.required_audio_count" :min="1" :max="5000" />
        </el-form-item>
        <el-form-item label="每人领取上限">
          <el-input-number v-model="editForm.claim_limit" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker
            v-model="editForm.deadline_at"
            type="datetime"
            placeholder="选填；到点任务标「已截止」"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
          />
          <div class="tip">发布后过截止时间 → 列表/看板标「已截止」；发布后不可再改（仅草稿可编辑）</div>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editForm.description" placeholder="任务说明（选填）" />
        </el-form-item>
        <el-form-item label="词条">
          <el-select
            v-model="editWordIds"
            multiple
            filterable
            remote
            :remote-method="searchEditWords"
            :loading="editWordLoading"
            placeholder="搜索并选择词条"
            style="width: 100%"
          >
            <el-option v-for="w in editWordOptions" :key="w.id" :label="w.content" :value="w.id" :disabled="w.occupied">
              <span>{{ w.content }}</span>
              <span class="opt-code">{{ w.code }}</span>
              <el-tag v-if="w.occupied" size="small" type="info" style="margin-left: 4px">已占用</el-tag>
            </el-option>
          </el-select>
          <div class="tip">已选 {{ editWordIds.length }} 条词条；输入关键词搜索加入或移除。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 查看任务词条 -->
    <el-dialog v-model="wordsVisible" :title="wordsTitle" width="760px">
      <el-table :data="taskWords" v-loading="taskWordsLoading" border size="small" max-height="480">
        <el-table-column prop="code" label="编号" width="100" show-overflow-tooltip />
        <el-table-column prop="dialect_point" label="方言点" width="150" show-overflow-tooltip />
        <el-table-column prop="content" label="词条内容" min-width="140" show-overflow-tooltip />
        <el-table-column prop="example_sentence" label="例句" min-width="180" show-overflow-tooltip />
        <el-table-column label="占用" width="70">
          <template #default="{ row }">
            <el-tag v-if="row.occupied" type="info" size="small">占用</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <span class="tip">「全部加入已选」把该任务未被占用的词条并入当前选择，自动跳过已占用</span>
        <el-button @click="wordsVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!taskWords.length" @click="importFromTask">全部加入已选</el-button>
      </template>
    </el-dialog>

    <!-- 领取管理（领取制）：查看每条领取，已录不可解绑，解绑后词条回池 -->
    <el-dialog v-model="claimsVisible" :title="claimsTitle" width="760px">
      <el-table :data="taskClaims" v-loading="claimsLoading" border size="small" max-height="480">
        <el-table-column prop="content" label="词条内容" min-width="160" show-overflow-tooltip />
        <el-table-column prop="nickname" label="发音人" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.nickname || `发音人#${row.speaker_id}` }}</template>
        </el-table-column>
        <el-table-column label="是否已录" width="90">
          <template #default="{ row }">
            <el-tag :type="row.recorded ? 'success' : 'info'" size="small">{{ row.recorded ? '已录' : '未录' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="领取时间" width="160">
          <template #default="{ row }">{{ row.claimed_at?.slice(0, 16).replace('T', ' ') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="danger"
              :disabled="row.recorded"
              @click="unbindClaim(row)"
            >解绑</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无领取记录</template>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'
import { useRegionStore } from '../stores/regions'

const auth = useAuthStore()
const regionStore = useRegionStore()

const cascaderProps = { value: 'code', label: 'name', children: 'children', checkStrictly: true, emitPath: true }

const form = reactive({ name: '', description: '', required_audio_count: 30, claim_limit: 10, is_demo: false, deadline_at: null })
const taskRegion = ref([])
const wordFilterRegion = ref([])
const wordKeyword = ref('')
const teams = ref([]) // 团队码列表（省管理员仅本省）
const selectedTeamCode = ref(null) // 创建表单选中的团队码

const words = ref([])
const wordsTable = ref(null)
const wordsLoading = ref(false)
const wordTotal = ref(0)
const wordPage = ref(1)
const wordPageSize = ref(20)
const selectedWords = ref(new Map()) // 已选词条：id -> 词条对象（清单展示/单个移除用）
const selectedVisible = ref(false) // 已选词条清单抽屉
const selectingAll = ref(false)

const tasks = ref([])
const tasksLoading = ref(false)
const taskTotal = ref(0)
const creating = ref(false)
const taskPage = ref(1)
const taskPageSize = ref(20)

const editVisible = ref(false)
const editing = ref(false)
const cleaning = ref(false) // 清理到期任务（后台完善 9）
const editForm = reactive({ id: null, name: '', description: '', required_audio_count: 30, claim_limit: 10, team_code: null, deadline_at: null })
const editWordIds = ref([])
const editWordOptions = ref([])
const editWordLoading = ref(false)

const wordsVisible = ref(false)
const wordsTitle = ref('')
const taskWords = ref([])
const taskWordsLoading = ref(false)

// 领取管理（领取制）
const claimsVisible = ref(false)
const claimsTitle = ref('')
const claimsTaskRow = ref(null) // 当前任务的列表行（解绑后刷新需要任务 id）
const taskClaims = ref([])
const claimsLoading = ref(false)

// 省管理员只能操作本省
const regionOptions = computed(() => {
  if (auth.isSuper) return regionStore.tree
  return regionStore.tree.filter((p) => p.code === auth.provinceCode)
})

function regionName(code) {
  return regionStore.nameOf(code)
}

// 选中团队后地区由团队码带出：区划级联锁死，仅省管理员手选时可自由改
const regionLocked = computed(() => !auth.isSuper || !!selectedTeamCode.value)

const selectedTeamInfo = computed(() => {
  const t = teams.value.find((x) => x.code === selectedTeamCode.value)
  return t ? `${regionName(t.province_code)}-${regionName(t.city_code)}` : ''
})

const editTeamRegion = computed(() => {
  const t = teams.value.find((x) => x.code === editForm.team_code)
  return t ? `${regionName(t.province_code)}-${regionName(t.city_code)}` : ''
})

function teamOf(code) {
  return teams.value.find((x) => x.code === code)
}

/** 创建表单选团队：地区由团队码带出并同步词条筛选 */
function onTeamChange(code) {
  const t = code ? teamOf(code) : null
  if (t) {
    taskRegion.value = [t.province_code, t.city_code]
  } else {
    taskRegion.value = []
  }
  onTaskRegionChange()
}

async function loadTeams() {
  try {
    teams.value = await request.get('/team-codes')
  } catch (e) {
    teams.value = []
  }
}

function onTaskRegionChange() {
  // 默认以任务投放区划筛选词条
  wordFilterRegion.value = [...taskRegion.value]
  wordPage.value = 1
  loadWords()
}

function regionParams(region) {
  const [p, c, d] = region || []
  const params = {}
  if (p) params.province_code = p
  if (c) params.city_code = c
  if (d) params.district_code = d
  return params
}

async function loadWords() {
  wordsLoading.value = true
  try {
    const data = await request.get('/words', {
      params: { page: wordPage.value, page_size: wordPageSize.value, keyword: wordKeyword.value, status: 'active', ...regionParams(wordFilterRegion.value) }
    })
    words.value = data.items
    wordTotal.value = data.total
    // 保持已选状态：服务端分页回来，仅同步当前页勾选
  } finally {
    wordsLoading.value = false
  }
}

function onSelectionChange(rows) {
  const next = new Map()
  rows.forEach((r) => next.set(r.id, r))
  // 合并到全局已选（保留其它页的勾选）
  selectedWords.value.forEach((w, id) => {
    const inCurrentPage = words.value.some((x) => x.id === id)
    if (!inCurrentPage) next.set(id, w)
  })
  selectedWords.value = next
}

/** 已选词条清单（供抽屉展示）与当前页已占用数（提示不可勾选） */
const selectedWordList = computed(() => [...selectedWords.value.values()])
/** 已选词条按方言点分组：[[point, words[]], ...] */
const selectedByPoint = computed(() => {
  const groups = new Map()
  selectedWordList.value.forEach((w) => {
    const k = w.dialect_point || '(未标方言点)'
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k).push(w)
  })
  return [...groups.entries()]
})
const occupiedCount = computed(() => words.value.filter((w) => w.occupied).length)

function clearSelection() {
  selectedWords.value = new Map()
  wordsTable.value?.clearSelection()
  loadWords()
}

/** 已选清单：单个移除，并同步当前页勾选态 */
function removeSelectedWord(id) {
  selectedWords.value.delete(id)
  const row = words.value.find((w) => w.id === id)
  if (row) wordsTable.value?.toggleRowSelection(row, false)
}

/** 全选当前页所有行（表头全选同效果），不影响其它页已选；有占用被跳过时提示 */
function selectPage() {
  const table = wordsTable.value
  if (!table) return
  const selectableRows = words.value.filter((w) => !w.occupied)
  const alreadyCheckedAll = selectableRows.length > 0 && selectableRows.every((w) => selectedWords.value.has(w.id))
  table.toggleAllSelection()
  const occ = words.value.filter((w) => w.occupied).length
  if (!alreadyCheckedAll && occ) {
    ElMessage.info(`已全选当前页，跳过 ${occ} 条已占用词条`)
  }
}

/** 跨页全选：抓取当前筛选下的全部词条（跨全部分页）并全部选中 */
async function selectAllFiltered() {
  selectingAll.value = true
  try {
    // 词条上千时用 page_size=500 分页抓取，减少请求次数
    const params = { page_size: 500, keyword: wordKeyword.value, status: 'active', ...regionParams(wordFilterRegion.value) }
    const all = []
    let page = 1
    while (true) {
      const data = await request.get('/words', { params: { page, ...params } })
      all.push(...data.items)
      if (page * 500 >= data.total) break
      page++
    }
    if (!all.length) {
      ElMessage.info('当前筛选下没有可选的词条')
      return
    }
    const selectable = all.filter((w) => !w.occupied)
    const occupiedCount = all.length - selectable.length
    if (!selectable.length) {
      ElMessage.info('当前筛选下词条均已被其它任务占用')
      return
    }
    try {
      await ElMessageBox.confirm(
        `将选中全部 ${selectable.length} 条匹配词条（跨全部分页），已选的保留。` +
        (occupiedCount ? `另有 ${occupiedCount} 条已占用将跳过。` : '') +
        '确定？',
        '跨页全选',
        { type: 'warning' }
      )
    } catch (e) { return }
    const table = wordsTable.value
    selectable.forEach((w) => {
      table.toggleRowSelection(w, true)
      selectedWords.value.set(w.id, w)
    })
    ElMessage.success(`已全选 ${selectable.length} 条${occupiedCount ? `（跳过 ${occupiedCount} 条已占用）` : ''}`)
  } finally {
    selectingAll.value = false
  }
}

async function createTask(publishAfter) {
  const [p, c, d] = taskRegion.value || []
  if (!p) {
    ElMessage.warning('请选择投放省份')
    return
  }
  creating.value = true
  try {
    const body = {
      name: form.name,
      description: form.description,
      province_code: p,
      city_code: c || null,
      district_code: d || null,
      team_code: selectedTeamCode.value || null,
      required_audio_count: form.required_audio_count,
      claim_limit: form.claim_limit,
      word_ids: [...selectedWords.value.keys()],
      is_demo: form.is_demo,
      deadline_at: toUtcIso(form.deadline_at)
    }
    const task = await request.post('/tasks', body)
    if (publishAfter) {
      await request.post(`/tasks/${task.id}/publish`)
      ElMessage.success('已创建并发布')
    } else {
      ElMessage.success('已保存草稿')
    }
    form.name = ''
    form.description = ''
    form.is_demo = false
    form.deadline_at = null
    selectedWords.value = new Map()
    selectedTeamCode.value = null
    if (auth.isSuper) {
      taskRegion.value = []
      wordFilterRegion.value = []
    }
    loadTasks()
  } finally {
    creating.value = false
  }
}

async function loadTasks() {
  tasksLoading.value = true
  try {
    const data = await request.get('/tasks', {
      params: { page: taskPage.value, page_size: taskPageSize.value }
    })
    tasks.value = data.items
    taskTotal.value = data.total
  } finally {
    tasksLoading.value = false
  }
}

async function publish(row) {
  await request.post(`/tasks/${row.id}/publish`)
  ElMessage.success('已发布')
  loadTasks()
}

async function openEdit(row) {
  Object.assign(editForm, {
    id: row.id,
    name: row.name || '',
    description: row.description || '',
    required_audio_count: row.required_audio_count,
    claim_limit: row.claim_limit ?? 10,
    team_code: row.team_code || null,
    deadline_at: toLocalInput(row.deadline_at)
  })
  // 预载已选词条
  try {
    const words = await request.get(`/tasks/${row.id}/words`)
    editWordOptions.value = words
    editWordIds.value = words.map((w) => w.id)
  } catch (e) {
    editWordOptions.value = []
    editWordIds.value = []
  }
  editVisible.value = true
}

/** 词条远程搜索：保留已选项，避免选中项从下拉消失显示成 id */
function mergeEditOptions(items) {
  const map = new Map()
  editWordOptions.value.forEach((w) => map.set(w.id, w))
  items.forEach((w) => map.set(w.id, w))
  editWordOptions.value = [...map.values()]
}

async function searchEditWords(query) {
  if (!query) return
  editWordLoading.value = true
  try {
    const data = await request.get('/words', {
      params: { keyword: query, page_size: 20, status: 'active', exclude_task_id: editForm.id || undefined }
    })
    mergeEditOptions(data.items)
  } finally {
    editWordLoading.value = false
  }
}

async function saveEdit() {
  if (!editForm.name || !editForm.name.trim()) {
    ElMessage.warning('任务名称不能为空')
    return
  }
  editing.value = true
  try {
    await request.patch(`/tasks/${editForm.id}`, {
      name: editForm.name.trim(),
      description: editForm.description || null,
      required_audio_count: editForm.required_audio_count,
      claim_limit: editForm.claim_limit,
      word_ids: editWordIds.value,
      team_code: editForm.team_code || null,
      deadline_at: toUtcIso(editForm.deadline_at)
    })
    ElMessage.success('已保存')
    editVisible.value = false
    loadTasks()
  } finally {
    editing.value = false
  }
}

async function closeTask(row) {
  try {
    await ElMessageBox.confirm(
      `关闭后小程序将不再展示任务「${row.name}」，已采集录音保留。确定关闭？`,
      '关闭确认',
      { type: 'warning' }
    )
  } catch (e) { return }
  await request.post(`/tasks/${row.id}/close`)
  ElMessage.success('已关闭')
  loadTasks()
}

async function reopenTask(row) {
  try {
    await ElMessageBox.confirm(
      `重新打开后小程序将重新展示任务「${row.name}」，发音人可继续采录，已采集录音保留。确定打开？`,
      '打开确认',
      { type: 'warning' }
    )
  } catch (e) { return }
  await request.post(`/tasks/${row.id}/reopen`)
  ElMessage.success('已打开')
  loadTasks()
}

async function removeTask(row) {
  const statusText = row.status === 'draft' ? '草稿' : row.status === 'published' ? '已发布' : '已关闭'
  const extra = row.status !== 'draft' ? '删除后小程序端将不再展示该任务。' : ''
  try {
    await ElMessageBox.confirm(
      `确定删除${statusText}任务「${row.name}」？${extra}删除后不可恢复。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch (e) { return }
  await request.delete(`/tasks/${row.id}`)
  ElMessage.success('已删除')
  loadTasks()
}

async function openWords(row) {
  wordsVisible.value = true
  wordsTitle.value = `词条清单 — ${row.name}`
  taskWordsLoading.value = true
  try {
    taskWords.value = await request.get(`/tasks/${row.id}/words`)
  } finally {
    taskWordsLoading.value = false
  }
}

/** 从当前任务把未占用的词条并入已选（跳过占用），便于快速创建同类任务 */
function importFromTask() {
  const ok = taskWords.value.filter((w) => !w.occupied)
  const skipped = taskWords.value.length - ok.length
  if (!ok.length) {
    ElMessage.info('该任务词条均已被占用，无法带入')
    return
  }
  ok.forEach((w) => selectedWords.value.set(w.id, w))
  ElMessage.success(skipped ? `已加入 ${ok.length} 条（跳过 ${skipped} 条已占用）` : `已加入 ${ok.length} 条`)
  wordsVisible.value = false
}

function statusLabel(s) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s
}
function statusTag(s) {
  return { draft: 'info', published: 'success', closed: 'danger' }[s] || 'info'
}

// 任务级进度（后台完善 4）：进度条按已录词条 / 任务词条总数，旁附通过数 + 完成状态 tag
function taskPct(row) {
  const total = row.word_count || 0
  return total ? Math.round(((row.recorded_count || 0) / total) * 100) : 0
}
function completionLabel(s) {
  return { in_progress: '进行中', near_complete: '接近完成', completed: '已完成', archived: '归档', expired: '已截止' }[s] || '进行中'
}
function completionTag(s) {
  return { in_progress: 'info', near_complete: 'warning', completed: 'success', archived: 'danger', expired: 'danger' }[s] || 'info'
}

/* —— 截止时间（后台完善 9）：本地输入 <-> UTC ISO，避免时区错位 —— */
function toLocalInput(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function toUtcIso(localInput) {
  if (!localInput) return null
  const d = new Date(localInput.replace(' ', 'T'))
  return isNaN(d.getTime()) ? null : d.toISOString()
}
function fmtDeadline(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function deadlineRemain(iso) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
  if (days > 0) return `剩 ${days} 天`
  if (days === 0) return '今天截止'
  return '已到期'
}

async function cleanupExpired() {
  try {
    await ElMessageBox.confirm(
      '将关闭所有「已发布且已过截止时间」的任务：小程序立即不再展示/采录，已采集录音保留。确定清理？',
      '清理到期任务',
      { type: 'warning', confirmButtonText: '清理' }
    )
  } catch (e) {
    return
  }
  cleaning.value = true
  try {
    const data = await request.post('/tasks/cleanup-expired')
    ElMessage.success(`已关闭 ${data.closed} 个到期任务`)
    loadTasks()
  } finally {
    cleaning.value = false
  }
}

async function openClaims(row) {
  claimsVisible.value = true
  claimsTitle.value = `领取管理 — ${row.name}`
  claimsTaskRow.value = row
  claimsLoading.value = true
  try {
    taskClaims.value = await request.get(`/tasks/${row.id}/claims`)
  } finally {
    claimsLoading.value = false
  }
}

/** 解绑领取：仅未录制可解绑（已录由后端 400 拦截），解绑后词条回池 */
async function unbindClaim(row) {
  const task = claimsTaskRow.value
  if (!task) return
  try {
    await ElMessageBox.confirm(
      `解绑后「${row.content}」将释放回池，其他人可领取；该发音人已录的录音不受影响。确定解绑？`,
      '解绑确认',
      { type: 'warning' }
    )
  } catch (e) { return }
  await request.delete(`/tasks/${task.id}/claims/${row.claim_id}`)
  ElMessage.success('已解绑')
  openClaims(task)
}

onMounted(async () => {
  await regionStore.ensureLoaded()
  // 省管理员默认锁本省
  if (!auth.isSuper && auth.provinceCode) {
    taskRegion.value = [auth.provinceCode]
    wordFilterRegion.value = [auth.provinceCode]
  }
  loadTeams()
  loadWords()
  loadTasks()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.selected-info {
  color: #909399;
  font-size: 13px;
}
.filter-bar {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.filter-group {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.filter-group--ops {
  justify-content: flex-end;
}
.occupied-hint {
  margin-bottom: 10px;
  color: #909399;
  font-size: 12px;
}
.drawer-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.point-group {
  margin-bottom: 14px;
}
.point-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  font-weight: 600;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 6px;
}
.selected-empty {
  color: #909399;
  font-size: 13px;
  padding: 40px 0;
  text-align: center;
}
.table-empty {
  padding: 20px 0;
  text-align: center;
}
.table-empty p {
  margin: 4px 0;
}
.pager {
  margin-top: 10px;
  justify-content: flex-end;
}
.actions {
  margin-top: 12px;
  text-align: right;
}
.tip {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}
.task-progress-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
}
.muted {
  color: #c0c4cc;
}
.deadline-expired {
  color: #f56c6c;
  font-weight: 600;
}
.opt-code {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
</style>

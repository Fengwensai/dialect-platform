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
        <span class="total">共 {{ total }} 条</span>
      </div>
    </el-card>

    <!-- 词条表格 -->
    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="code" label="编号" width="100" show-overflow-tooltip />
        <el-table-column prop="dialect_point" label="方言点" width="150" show-overflow-tooltip />
        <el-table-column prop="content" label="词条内容" min-width="130" show-overflow-tooltip />
        <el-table-column prop="example_sentence" label="例句" min-width="170" show-overflow-tooltip />
        <el-table-column prop="pronunciation_hint" label="发音提示" width="110" show-overflow-tooltip />
        <el-table-column label="行政区划" width="200">
          <template #default="{ row }">
            <span v-if="row.province_code">{{ regionName(row.province_code) }}<template v-if="row.city_code">-{{ regionName(row.city_code) }}</template><template v-if="row.district_code">-{{ regionName(row.district_code) }}</template></span>
            <el-tag v-else type="warning" size="small">未匹配</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-switch
              :model-value="row.status === 'active'"
              @change="(val) => toggleStatus(row, val)"
              active-text="启用"
              inactive-text="禁用"
              inline-prompt
            />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="导入时间" width="170">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="openMerge(row)">合并</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, RefreshLeft } from '@element-plus/icons-vue'
import request from '../api/request'
import { useRegionStore } from '../stores/regions'

const regionStore = useRegionStore()
const loading = ref(false)
const saving = ref(false)
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

function regionName(code) {
  return regionStore.nameOf(code)
}

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
}

function reset() {
  keyword.value = ''
  filterRegion.value = []
  filterStatus.value = ''
  page.value = 1
  load()
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
.merge-tip {
  margin: 0 0 14px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
</style>

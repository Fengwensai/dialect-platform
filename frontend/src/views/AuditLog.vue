<template>
  <div>
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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
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

onMounted(load)
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
.detail-box {
  padding: 10px 14px;
}
.detail-json {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #303133;
  background: #f5f6f8;
  border-radius: 4px;
  padding: 8px 10px;
}
.detail-empty {
  color: #c0c4cc;
  font-size: 13px;
  padding: 10px 14px;
}
</style>

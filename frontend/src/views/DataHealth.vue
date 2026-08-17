<template>
  <div>
    <!-- 巡检汇总 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <div class="filter-bar">
        <div v-if="report && report.total === 0" class="health-ok">
          <el-icon class="ok-icon"><CircleCheckFilled /></el-icon>
          <span>数据健康 ✓ 无孤儿引用（所有逻辑引用均有对应父行）</span>
        </div>
        <template v-else-if="report">
          <div class="health-bad">
            <el-icon class="bad-icon"><WarningFilled /></el-icon>
            <span>发现 <b class="bad-count">{{ report.total }}</b> 条孤儿引用：</span>
            <el-tag
              v-for="c in report.categories.filter(c => c.count > 0)"
              :key="c.key"
              :type="tagType(c.key)"
              size="small"
              class="cat-tag"
            >
              {{ c.name }} {{ c.count }}
            </el-tag>
          </div>
          <el-button type="danger" :loading="repairing" :icon="MagicStick" @click="repairAll">
            一键修复
          </el-button>
        </template>
        <el-button :icon="Refresh" @click="load" :loading="loading">刷新巡检</el-button>
      </div>
    </el-card>

    <!-- 孤儿明细 -->
    <el-card shadow="never">
      <div v-if="rows.length" class="filter-bar" style="margin-bottom: 10px">
        <el-select v-model="filterCategory" placeholder="全部分类" clearable style="width: 200px" @change="filterCategory = filterCategory || ''">
          <el-option
            v-for="c in report?.categories"
            :key="c.key"
            :label="`${c.name}（${c.count}）`"
            :value="c.key"
          />
        </el-select>
        <span class="total">共 {{ filteredRows.length }} 条明细（每类最多展示 200 条）</span>
      </div>

      <el-table :data="filteredRows" v-loading="loading" border stripe>
        <el-table-column label="分类" width="140">
          <template #default="{ row }">
            <el-tag :type="tagType(row.catKey)" size="small">{{ row.catName }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="说明" min-width="240" />
        <el-table-column label="缺失引用" width="120">
          <template #default="{ row }">
            <span class="ref-code">#{{ row.ref }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="danger" size="small" :loading="repairing" @click="repairRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && report && report.total === 0" description="数据健康，无孤儿引用" :image-size="80" />
      <el-empty v-else-if="!loading && report && rows.length === 0" description="该分类无明细" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheckFilled, MagicStick, Refresh, WarningFilled } from '@element-plus/icons-vue'
import request from '../api/request'

const loading = ref(false)
const repairing = ref(false)
const report = ref(null)
const filterCategory = ref('')

const rows = computed(() => {
  if (!report.value) return []
  return report.value.categories.flatMap((c) =>
    c.items.map((item) => ({ ...item, catKey: c.key, catName: c.name }))
  )
})

const filteredRows = computed(() =>
  filterCategory.value ? rows.value.filter((r) => r.catKey === filterCategory.value) : rows.value
)

function tagType(key) {
  if (key.startsWith('recording_')) return 'danger'
  if (key.startsWith('item_')) return 'warning'
  if (key.startsWith('claim_')) return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    report.value = await request.get('/data-health')
  } finally {
    loading.value = false
  }
}

async function repairAll() {
  const total = report.value?.total || 0
  try {
    await ElMessageBox.confirm(
      `将删除全部 ${total} 条孤儿引用：孤儿录音（含音频文件）/任务条目/领取记录/协议记录。此操作不可撤销，确定继续？`,
      '一键修复孤儿引用',
      { type: 'warning', confirmButtonText: '确定修复', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  await doRepair({})
}

async function repairRow(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除该孤儿记录？\n${row.detail}（缺失引用 #${row.ref}）`,
      '删除单条孤儿',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await doRepair({ category: row.catKey, ids: [row.id] })
}

async function doRepair(body) {
  repairing.value = true
  try {
    const res = await request.post('/data-health/repair', body)
    const parts = Object.entries(res.deleted)
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `${k}=${n}`)
    ElMessage.success(`已修复 ${res.total} 条孤儿引用（${parts.join('，') || '无'}）`)
    filterCategory.value = ''
    await load()
  } finally {
    repairing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.health-ok {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #67c23a;
  font-weight: 600;
}
.health-bad {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ok-icon {
  font-size: 18px;
}
.bad-icon {
  font-size: 18px;
  color: #e6a23c;
}
.bad-count {
  color: #f56c6c;
  font-size: 16px;
}
.cat-tag {
  margin-right: 2px;
}
.total {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.ref-code {
  font-family: monospace;
  color: var(--el-text-color-regular);
}
</style>

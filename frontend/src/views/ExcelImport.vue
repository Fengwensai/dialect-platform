<template>
  <div class="excel-import">
    <!-- 第一步：上传 -->
    <el-card v-if="!preview" shadow="never">
      <template #header><b>上传词表 Excel</b></template>
      <el-upload
        drag
        action="#"
        accept=".xlsx,.xlsm"
        :auto-upload="false"
        :limit="1"
        :show-file-list="false"
        :on-change="handleUpload"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">将 Excel 拖到此处，或<em>点击选择</em></div>
        <div class="el-upload__tip">支持 .xlsx / .xlsm；默认列头：编号、方言点、词条内容、例句、备注（可选发音提示）</div>
      </el-upload>
    </el-card>

    <!-- 第二步：列映射 + 预览 -->
    <template v-else>
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <b>文件：{{ preview.filename }}（工作表：{{ preview.sheet_name }}，共 {{ preview.total_rows }} 条）</b>
            <div>
              <el-button @click="reset">重新选择文件</el-button>
              <el-button type="primary" :loading="importing" @click="onImport">确认导入</el-button>
            </div>
          </div>
        </template>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="导入时会按『方言点』文本自动匹配省市区；匹配不到的以文件名省份兜底或留空，可在词条管理中手动修正。"
        />

        <div class="map-row">
          <span class="map-title">列映射：</span>
          <div v-for="(h, i) in preview.headers" :key="i" class="map-item">
            <span class="map-col">{{ h || `列${i + 1}` }}</span>
            <el-select v-model="mapping[String(i)]" placeholder="不导入" clearable style="width: 150px" size="small">
              <el-option v-for="f in FIELD_OPTIONS" :key="f.value" :label="f.label" :value="f.value" />
            </el-select>
          </div>
        </div>

        <el-table :data="preview.rows" border size="small" max-height="460" :row-class-name="rowClass">
          <el-table-column type="index" label="#" width="48" />
          <el-table-column prop="row_index" label="行号" width="70" />
          <el-table-column prop="code" label="编号" width="90" show-overflow-tooltip />
          <el-table-column prop="dialect_point" label="方言点" width="160" show-overflow-tooltip />
          <el-table-column prop="content" label="词条内容" min-width="140" show-overflow-tooltip />
          <el-table-column prop="example_sentence" label="例句" min-width="180" show-overflow-tooltip />
          <el-table-column prop="remark" label="备注" min-width="100" show-overflow-tooltip />
          <el-table-column label="区划匹配" width="110">
            <template #default="{ row }">
              <el-tag :type="row.region_matched ? 'success' : 'warning'" size="small">
                {{ row.region_matched ? '已匹配' : '待确认' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 导入结果 -->
    <el-dialog v-model="resultVisible" title="导入结果" width="560px">
      <template v-if="result">
        <el-result
          :icon="result.fail_count > 0 ? 'warning' : 'success'"
          :title="`成功 ${result.success_count} 条，失败 ${result.fail_count} 条`"
        >
          <template #extra>
            <el-table v-if="result.errors.length" :data="result.errors" border size="small" max-height="300">
              <el-table-column prop="row" label="行号" width="70" />
              <el-table-column prop="content" label="内容" width="140" show-overflow-tooltip />
              <el-table-column prop="reason" label="原因" show-overflow-tooltip />
            </el-table>
          </template>
        </el-result>
      </template>
      <template #footer>
        <el-button type="primary" @click="resultVisible = false; reset()">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api/request'

const FIELD_OPTIONS = [
  { value: 'code', label: '编号' },
  { value: 'dialect_point', label: '方言点' },
  { value: 'content', label: '词条内容' },
  { value: 'example_sentence', label: '例句' },
  { value: 'remark', label: '备注' },
  { value: 'pronunciation_hint', label: '发音提示' }
]
const EMPTY_ROW = { code: '', dialect_point: '', content: '', example_sentence: '', remark: '', pronunciation_hint: '' }

const preview = ref(null)
const mapping = reactive({})
const importing = ref(false)
const resultVisible = ref(false)
const result = ref(null)

async function handleUpload(file) {
  if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
    ElMessage.warning('仅支持 .xlsx / .xlsm 格式')
    return
  }
  try {
    const fd = new FormData()
    fd.append('file', file.raw)
    const data = await request.post('/excel/upload', fd)
    preview.value = data
    Object.keys(mapping).forEach((k) => delete mapping[k])
    Object.assign(mapping, data.mapping)
  } catch (e) {
    /* 拦截器已提示 */
  }
}

function reset() {
  preview.value = null
  Object.keys(mapping).forEach((k) => delete mapping[k])
  result.value = null
}

function rowClass({ row }) {
  return row.region_matched ? '' : 'row-warn'
}

async function onImport() {
  const rows = preview.value.raw_rows.map((cells, i) => {
    const src = preview.value.rows[i] || { row_index: i + 2 }
    const obj = { row_index: src.row_index, ...EMPTY_ROW }
    for (const colStr in mapping) {
      const field = mapping[colStr]
      const idx = Number(colStr)
      if (field && cells[idx] != null) obj[field] = String(cells[idx]).trim()
    }
    return obj
  })
  importing.value = true
  try {
    result.value = await request.post('/excel/import', {
      filename: preview.value.filename,
      mapping: { ...mapping },
      rows
    })
    resultVisible.value = true
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.upload-icon {
  font-size: 60px;
  color: var(--el-text-color-placeholder);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.map-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.map-title {
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.map-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.map-col {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<style>
.excel-import .el-table .row-warn td {
  background-color: rgba(230, 162, 60, 0.12);
}
</style>

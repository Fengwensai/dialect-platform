<template>
  <el-card shadow="never">
    <template #header>
      <div class="header">
        <b>中国行政区划（省-市-区）</b>
        <span class="tip">共 {{ totalCount }} 条 · 由内置静态数据灌入，后续可接入高德/腾讯区划 API 同步</span>
      </div>
    </template>

    <div class="tree-wrap">
      <el-tree
        :data="regionStore.tree"
        :props="{ label: 'name', children: 'children' }"
        default-expand-all
        node-key="code"
        :expand-on-click-node="false"
      >
        <template #default="{ node, data }">
          <span class="node">
            <span>{{ node.label }}</span>
            <span class="node-code">{{ data.code }}</span>
          </span>
        </template>
      </el-tree>
    </div>
  </el-card>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRegionStore } from '../stores/regions'

const regionStore = useRegionStore()

const totalCount = computed(() => {
  let n = 0
  const walk = (nodes) => {
    for (const x of nodes) {
      n++
      if (x.children?.length) walk(x.children)
    }
  }
  walk(regionStore.tree)
  return n
})

onMounted(() => regionStore.ensureLoaded())
</script>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tip {
  font-size: 12px;
  color: #909399;
}
.tree-wrap {
  max-height: 70vh;
  overflow: auto;
}
.node {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.node-code {
  font-size: 12px;
  color: #b0b4bb;
  font-family: monospace;
}
</style>

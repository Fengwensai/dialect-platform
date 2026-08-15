import { ref, watch } from 'vue'

/**
 * 筛选条件本地持久化（后台完善 9）：刷新/重进页面筛选不丢。
 *
 * 用法：const { keyword, filterStatus, pageSize } = usePersistedFilters('review-filters-v1', {
 *   keyword: '', filterStatus: 'pending', pageSize: 20
 * })
 *
 * - 返回与 defaults 同 key 的一组 ref，初始值从 localStorage JSON 读（解析失败/不存在回退默认值）。
 * - watch 深比较写回 localStorage；reset() 把值设回默认即可「清空」。
 * - 约定不持久化 page——刷新回到第 1 页，避免翻页中间态误导。
 */
export function usePersistedFilters(storageKey, defaults) {
  let saved = {}
  try {
    const raw = localStorage.getItem(storageKey)
    if (raw) saved = JSON.parse(raw)
  } catch (e) {
    saved = {}
  }

  const state = {}
  for (const [k, d] of Object.entries(defaults)) {
    state[k] = ref(k in saved ? saved[k] : d)
  }

  watch(
    () => Object.keys(state).map((k) => state[k].value),
    () => {
      const toSave = {}
      for (const [k, r] of Object.entries(state)) toSave[k] = r.value
      try {
        localStorage.setItem(storageKey, JSON.stringify(toSave))
      } catch (e) {
        // 存储满 / 隐私模式等异常静默，不阻塞使用
      }
    },
    { deep: true }
  )

  return state
}

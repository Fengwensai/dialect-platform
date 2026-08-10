import { defineStore } from 'pinia'
import request from '../api/request'

export const useRegionStore = defineStore('regions', {
  state: () => ({
    tree: [],
    nameMap: {},
    loaded: false
  }),
  actions: {
    async ensureLoaded() {
      if (this.loaded) return
      const tree = await request.get('/regions/tree')
      this.tree = tree
      const nameMap = {}
      const walk = (nodes) => {
        for (const n of nodes) {
          nameMap[n.code] = n.name
          if (n.children?.length) walk(n.children)
        }
      }
      walk(tree)
      this.nameMap = nameMap
      this.loaded = true
    },
    nameOf(code) {
      return (code && this.nameMap[code]) || code || '-'
    },
    // 构建省市区级联值：[省code, 市code, 区code]
    cascaderValue(province, city, district) {
      const v = []
      if (province) v.push(province)
      if (city) v.push(city)
      if (district) v.push(district)
      return v
    }
  }
})

// 领任务页：仅展示我绑定属地（省+市）的已发布任务，显示我的已录进度
// 领取制（阶段十一）：卡片显示 总词条/已领/可领，可在此追加领取
const api = require('../../utils/api')
const region = require('../../utils/region')
const speaker = require('../../utils/speaker')

const share = require('../../utils/share')

Page({
  // 转发（右上角「…」菜单）：整包原未实现 onShareAppMessage 导致置灰，挂统一默认转发
  onShareAppMessage: share.onShareAppMessage,
  data: {
    regionText: '', // 属地展示文本，如「辽宁·沈阳」
    tasks: [],
    loading: true,
    // 领取条数弹窗（复用首页绑定团队弹窗样式）
    claimVisible: false,
    claimTaskId: 0,
    claimMax: 0, // 本次最多可领（= 当前可领数）
    claimInput: '',
    claimFocus: false,
    claiming: false
  },

  onShow() {
    if (!speaker.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 600)
      return
    }
    this.loadRegion()
    this.loadTasks()
  },

  onPullDownRefresh() {
    this.loadRegion()
    this.loadTasks().then(
      () => wx.stopPullDownRefresh(),
      () => wx.stopPullDownRefresh()
    )
  },

  // 属地由团队码绑定决定，服务端按此过滤任务，这里只展示名称
  loadRegion() {
    const sp = speaker.getSpeaker() || {}
    if (!sp.province_code) {
      this.setData({ regionText: '' })
      return
    }
    region
      .regionText(sp.province_code, sp.city_code || '')
      .then((t) => this.setData({ regionText: t }))
      .catch(() => this.setData({ regionText: sp.province_code }))
  },

  loadTasks() {
    this.setData({ loading: true })
    return api
      .request('/api/mp/tasks')
      .then((data) => {
        // 进度条目标改为「已领数」（我领的才需要录）；领取制前已录的历史数据兜底取大
        const tasks = (data.items || []).map((t) => {
          const claimed = t.my_claimed || 0
          const rec = t.recorded_count || 0
          const target = Math.max(claimed, rec)
          return Object.assign({}, t, {
            claimTarget: target,
            bar_percent: target ? Math.min(100, Math.round((rec / target) * 100)) : 0,
            claimBtnText:
              t.claimable > 0 ? '领取' : claimed > 0 ? '已领满' : '无可领'
          })
        })
        this.setData({ tasks, loading: false })
      })
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({
          title: (err && err.message) || '任务加载失败',
          icon: 'none'
        })
      })
  },

  goWords(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/words/words?taskId=' + id })
  },

  // —— 领取条数弹窗 ——
  openClaim(e) {
    const id = e.currentTarget.dataset.id
    const task = this.data.tasks.find((t) => t.id === id)
    if (!task || task.claimable <= 0) return
    this.setData({
      claimVisible: true,
      claimTaskId: id,
      claimMax: task.claimable,
      claimInput: String(Math.min(task.claimable, 10)),
      claimFocus: true
    })
  },

  closeClaim() {
    if (this.data.claiming) return
    this.setData({ claimVisible: false, claimTaskId: 0, claimInput: '' })
  },

  noop() {},

  onClaimInput(e) {
    this.setData({ claimInput: e.detail.value })
  },

  onClaimFocus() {
    this.setData({ claimFocus: true })
  },

  onClaimBlur() {
    this.setData({ claimFocus: false })
  },

  doClaim() {
    const n = Number(this.data.claimInput)
    if (!/^[1-9]\d*$/.test(this.data.claimInput) || n < 1) {
      wx.showToast({ title: '请输入有效的领取条数', icon: 'none' })
      return
    }
    const max = this.data.claimMax
    if (n > max) {
      wx.showToast({ title: '最多可领 ' + max + ' 条', icon: 'none' })
      return
    }
    this.setData({ claiming: true })
    api
      .claimWords(this.data.claimTaskId, n)
      .then(() => {
        this.setData({ claiming: false, claimVisible: false, claimTaskId: 0 })
        wx.showToast({ title: '已领取 ' + n + ' 条，去录音吧', icon: 'success' })
        return this.loadTasks()
      })
      .catch((err) => {
        this.setData({ claiming: false })
        wx.showToast({ title: (err && err.message) || '领取失败', icon: 'none' })
      })
  }
})

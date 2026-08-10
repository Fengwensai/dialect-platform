// 领任务页：仅展示我绑定属地（省+市）的已发布任务，显示我的已录进度
const api = require('../../utils/api')
const region = require('../../utils/region')
const speaker = require('../../utils/speaker')

Page({
  data: {
    regionText: '', // 属地展示文本，如「辽宁·沈阳」
    tasks: [],
    loading: true
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
        // 进度条按「需录条数（required_audio_count）」为目标，与已录数一致
        const tasks = (data.items || []).map((t) => {
          const req = t.required_audio_count || 0
          const rec = t.recorded_count || 0
          return Object.assign({}, t, {
            bar_percent: req ? Math.min(100, Math.round((rec / req) * 100)) : 0
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
  }
})

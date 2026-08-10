// 审核进度详情页：总体汇总 + 按任务拆分的已通过/待审核/需重录
// 数据来源：GET /api/mp/tasks（任务列表）+ GET /api/mp/recordings/progress?task_id=X（每任务进度）
const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    error: '',
    overview: { recorded: 0, approved: 0, pending: 0, rejected: 0 },
    tasks: [] // { taskId, taskName, wordCount, recorded, approved, pending, rejected, percent }
  },

  onShow() {
    // 首次进入带加载态；从词条页重录返回后静默刷新，保留旧数据不闪屏
    if (this._loaded) this.load({ silent: true })
    else this.load()
  },

  onPullDownRefresh() {
    this.load({ silent: true }).then(
      () => wx.stopPullDownRefresh(),
      () => wx.stopPullDownRefresh()
    )
  },

  load(opts) {
    opts = opts || {}
    if (!opts.silent) this.setData({ loading: true, error: '' })
    return this._fetch()
      .then(({ overview, tasks }) => {
        this._loaded = true
        this.setData({ loading: false, error: '', overview, tasks })
      })
      .catch((err) => {
        if (opts.silent) {
          // 静默刷新失败：保留旧数据，轻提示
          this.setData({ loading: false })
          wx.showToast({ title: '刷新失败，请检查网络', icon: 'none' })
          return
        }
        this._loaded = true
        this.setData({ loading: false, error: (err && err.message) || '加载失败，请检查网络' })
      })
  },

  /** 拉取任务列表 + 每个任务的审核进度，汇总总体 */
  _fetch() {
    return api.request('/api/mp/tasks').then((data) => {
      const list = data.items || []
      // 并行拉取每任务进度；单个失败不拖垮整页（该任务进度按 0 展示）
      const jobs = list.map((t) =>
        api
          .request('/api/mp/recordings/progress?task_id=' + t.id)
          .then((p) => ({
            taskId: t.id,
            taskName: t.name,
            wordCount: p.total_words || t.word_count || 0,
            recorded: p.recorded || 0,
            approved: p.approved || 0,
            pending: p.pending || 0,
            rejected: p.rejected || 0
          }))
          .catch(() => ({
            taskId: t.id,
            taskName: t.name,
            wordCount: t.word_count || 0,
            recorded: 0,
            approved: 0,
            pending: 0,
            rejected: 0
          }))
      )
      return Promise.all(jobs).then((tasks) => {
        const overview = tasks.reduce(
          (acc, t) => {
            acc.recorded += t.recorded
            acc.approved += t.approved
            acc.pending += t.pending
            acc.rejected += t.rejected
            return acc
          },
          { recorded: 0, approved: 0, pending: 0, rejected: 0 }
        )
        tasks.forEach((t) => {
          t.percent = t.wordCount
            ? Math.min(100, Math.round((t.recorded / t.wordCount) * 100))
            : 0
        })
        return { overview, tasks }
      })
    })
  },

  /** 点击任务卡片 → 词条页（自带待审核/已通过/需重录 chip，可重录） */
  goTask(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    wx.navigateTo({ url: '/pages/words/words?taskId=' + id })
  }
})

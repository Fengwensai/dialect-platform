// 任务词条页：逐条录音（后端已录状态 + 本地队列待传状态）
const api = require('../../utils/api')
const speaker = require('../../utils/speaker')
const queue = require('../../utils/queue')

Page({
  data: {
    taskId: 0,
    taskName: '',
    total: 0,
    recorded: 0,
    redoCount: 0,
    words: [],
    loading: true
  },

  onLoad(options) {
    this.setData({ taskId: Number(options.taskId) || 0 })
  },

  onShow() {
    if (!speaker.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 600)
      return
    }
    this.loadWords()
  },

  onPullDownRefresh() {
    Promise.resolve(this.loadWords()).then(
      () => wx.stopPullDownRefresh(),
      () => wx.stopPullDownRefresh()
    )
  },

  loadWords() {
    const taskId = this.data.taskId
    if (!taskId) return
    this.setData({ loading: true })
    return api
      .request('/api/mp/tasks/' + taskId + '/words')
      .then((data) => {
        const items = data.items || []
        // 合并本地队列状态：录了但还没上传的词条显示"待上传/上传中"
        const localMap = {}
        queue.list().forEach((it) => {
          if (it.status === 'error') return
          localMap[String(it.taskId) + ':' + String(it.wordId)] = it.status
        })
        // 派生展示字段：chip（样式类）/ chipText / btnText，按「本地队列 → 审核状态」优先级
        items.forEach((w) => {
          const ls = localMap[String(taskId) + ':' + w.word_id]
          if (ls) {
            w.recorded = true
            w.localStatus = ls // pending | uploading | done
          } else {
            w.localStatus = ''
          }
          const st = w.status // pending | approved | rejected | null
          let chip = 'todo'
          let chipText = '未录'
          if (w.localStatus === 'pending') {
            chip = 'pending'
            chipText = '待上传'
          } else if (w.localStatus === 'uploading') {
            chip = 'uploading'
            chipText = '上传中'
          } else if (st === 'rejected') {
            chip = 'reject'
            chipText = '需重录'
          } else if (st === 'approved') {
            chip = 'done'
            chipText = '已通过'
          } else if (st === 'pending') {
            chip = 'pending'
            chipText = '待审核'
          }
          w.chip = chip
          w.chipText = chipText
          w.btnText = w.recorded ? '重录' : '录音'
          // 已通过且有审核转写时，展示「普通话/方言转写」参考
          w.hasTranscript = st === 'approved' && !!(w.mandarin_transcript || w.dialect_transcript)
        })
        const recorded = items.filter((w) => w.recorded).length
        const redoCount = items.filter((w) => w.status === 'rejected').length
        this.setData({
          taskName: (data.task && data.task.name) || '',
          total: items.length,
          recorded,
          redoCount,
          words: items,
          loading: false
        })
      })
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({
          title: (err && err.message) || '词条加载失败',
          icon: 'none'
        })
      })
  },

  record(e) {
    const id = e.currentTarget.dataset.id
    const it = this.data.words.find((w) => w.word_id === id)
    if (!it) return
    wx.navigateTo({
      url:
        '/pages/record/record?taskId=' +
        this.data.taskId +
        '&wordId=' +
        it.word_id +
        '&content=' +
        encodeURIComponent(it.content)
    })
  }
})

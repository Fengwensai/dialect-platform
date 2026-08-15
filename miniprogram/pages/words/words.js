// 任务词条页：逐条录音（后端已录状态 + 本地队列待传状态）
// 领取制（阶段十一）：列表 = 我领取的词条；头部可查看 已领/可领 并追加领取，未录制可退回
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
    loading: true,
    // 领取统计（MpClaimStats）
    claim: { task_word_total: 0, claim_limit: 10, my_claimed: 0, claimable: 0, available: 0 },
    claimMax: 0,
    // 领取条数弹窗
    claimVisible: false,
    claimInput: '',
    claimFocus: false,
    claiming: false
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
        const claim = data.claim || {}
        // 合并本地队列状态：录了但还没上传的词条显示"待上传/上传中"。
        // error/claimLost 不合并（失败/未领取的词条按后端真实状态展示，避免误导）。
        const localMap = {}
        queue.list().forEach((it) => {
          if (it.status === 'error' || it.status === 'claimLost') return
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
            // 驳回详细原因只在录音界面透出（record 页），卡片仅留「需重录」红标，避免撑乱布局
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
          claim,
          claimMax: claim.claimable || 0,
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
        encodeURIComponent(it.content) +
        '&taskName=' +
        encodeURIComponent(this.data.taskName || '')
    })
  },

  // —— 追加领取 ——
  openClaim() {
    if (this.data.claimMax <= 0) {
      wx.showToast({ title: '当前无可领取词条', icon: 'none' })
      return
    }
    this.setData({
      claimVisible: true,
      claimInput: String(Math.min(this.data.claimMax, 10)),
      claimFocus: true
    })
  },

  closeClaim() {
    if (this.data.claiming) return
    this.setData({ claimVisible: false, claimInput: '' })
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
    if (n > this.data.claimMax) {
      wx.showToast({ title: '最多可领 ' + this.data.claimMax + ' 条', icon: 'none' })
      return
    }
    this.setData({ claiming: true })
    api
      .claimWords(this.data.taskId, n)
      .then(() => {
        this.setData({ claiming: false, claimVisible: false })
        wx.showToast({ title: '已领取 ' + n + ' 条', icon: 'success' })
        return this.loadWords()
      })
      .catch((err) => {
        this.setData({ claiming: false })
        wx.showToast({ title: (err && err.message) || '领取失败', icon: 'none' })
      })
  },

  // —— 退回未录制词条 ——
  release(e) {
    const id = e.currentTarget.dataset.id
    const it = this.data.words.find((w) => w.word_id === id)
    if (!it || it.recorded) return
    wx.showModal({
      title: '退回词条',
      content: '退回后「' + it.content + '」将释放给其他人领取，确认退回？',
      confirmText: '退回',
      confirmColor: '#e53e3e',
      success: (r) => {
        if (!r.confirm) return
        api
          .releaseClaim(this.data.taskId, id)
          .then(() => {
            wx.showToast({ title: '已退回', icon: 'success' })
            return this.loadWords()
          })
          .catch((err) => {
            wx.showToast({ title: (err && err.message) || '退回失败', icon: 'none' })
          })
      }
    })
  }
})

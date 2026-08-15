// 队列页：列表 / 逐条试听·重录·删除 / 批量删除 / 一键上传 / 清空已完成
const queue = require('../../utils/queue')
const { formatDuration, formatBytes } = require('../../utils/fmt')

const STATUS_TEXT = {
  pending: '待上传',
  uploading: '上传中',
  done: '已完成',
  error: '失败',
  claimLost: '未领取' // 领取制：词条未领取/已解绑，上传被拒，需先领取
}

Page({
  data: {
    items: [],
    pendingCount: 0,
    flushing: false,
    selectMode: false, // 批量删除模式
    selected: {}, // id -> true，选中集合（对象便于快速查找）
    selectedCount: 0,
    storageText: '', // 本轮5 本地录音占用
    cleanableCount: 0 // 本轮5 可清理（已完成/失效）条数
  },

  onShow() {
    this.refresh()
  },

  onUnload() {
    if (this._audio) {
      this._audio.stop()
      this._audio.destroy()
    }
  },

  onPullDownRefresh() {
    this.refresh()
    wx.stopPullDownRefresh()
  },

  refresh() {
    const selected = this.data.selected || {}
    const items = queue.list().map((it) =>
      Object.assign({}, it, {
        durationText: formatDuration(it.durationMs),
        statusText: STATUS_TEXT[it.status] || it.status,
        checked: !!selected[it.id]
      })
    )
    // 本轮5 存储占用 + 可清理条数
    const used = queue.storageUsed()
    this.setData({
      items,
      pendingCount: items.filter((x) => x.status === 'pending').length,
      selectedCount: items.filter((x) => x.checked).length,
      storageText: formatBytes(used.bytes) + (used.files ? ' · ' + used.files + ' 个文件' : ''),
      cleanableCount: items.filter((x) => x.status === 'done' || x.status === 'claimLost').length
    })
  },

  play(e) {
    const id = e.currentTarget.dataset.id
    const it = this.data.items.find((x) => x.id === id)
    if (!it || !it.wavPath) {
      wx.showToast({ title: '录音文件不存在', icon: 'none' })
      return
    }
    if (!this._audio) this._audio = wx.createInnerAudioContext()
    this._audio.stop()
    this._audio.src = it.wavPath
    this._audio.play()
  },

  /** 重录：删本地文件后跳录音页重新念（仅对未失败项） */
  rerecord(e) {
    const id = e.currentTarget.dataset.id
    const it = this.data.items.find((x) => x.id === id)
    if (!it) return
    queue.remove(id)
    this.refresh()
    wx.navigateTo({
      url:
        '/pages/record/record?taskId=' +
        it.taskId +
        '&wordId=' +
        it.wordId +
        '&content=' +
        encodeURIComponent(it.content || '')
    })
  },

  /** 重试：失败项直接用已存文件重新上传（不删文件） */
  retryUpload(e) {
    const id = e.currentTarget.dataset.id
    const it = this.data.items.find((x) => x.id === id)
    if (!it) return
    if (this.data.flushing) {
      wx.showToast({ title: '正在上传中，请稍后', icon: 'none' })
      return
    }
    queue
      .retry(id, { onItem: () => this.refresh() })
      .then((r) => {
        this.refresh()
        if (r && r.skipped) return
        wx.showToast({
          title: r && r.ok ? '重试成功' : '重试失败，可再次重试',
          icon: (r && r.ok) ? 'success' : 'none'
        })
      })
  },

  /** 去领取：未领取词条直达任务词条页领取后再回来传 */
  goClaim(e) {
    const id = e.currentTarget.dataset.id
    const it = this.data.items.find((x) => x.id === id)
    if (!it) return
    wx.navigateTo({ url: '/pages/words/words?taskId=' + it.taskId })
  },

  remove(e) {
    const id = e.currentTarget.dataset.id
    wx.showModal({
      title: '删除录音',
      content: '删除后需重新录制，确认？',
      success: (r) => {
        if (r.confirm) {
          queue.remove(id)
          this.refresh()
        }
      }
    })
  },

  // —— 批量删除 ——
  toggleSelectMode() {
    if (this.data.selectMode) {
      // 退出选择模式
      this.setData({ selectMode: false, selected: {}, selectedCount: 0 })
    } else {
      this.setData({ selectMode: true, selected: {}, selectedCount: 0 })
    }
    this.refresh()
  },

  toggleItem(e) {
    if (!this.data.selectMode) return
    const id = e.currentTarget.dataset.id
    const selected = Object.assign({}, this.data.selected)
    if (selected[id]) delete selected[id]
    else selected[id] = true
    this.setData({ selected })
    this.refresh()
  },

  selectAll() {
    const selected = {}
    this.data.items.forEach((x) => {
      selected[x.id] = true
    })
    this.setData({ selected })
    this.refresh()
  },

  clearSelectAll() {
    this.setData({ selected: {}, selectedCount: 0 })
    this.refresh()
  },

  removeSelected() {
    const ids = this.data.items.filter((x) => x.checked).map((x) => x.id)
    if (!ids.length) {
      wx.showToast({ title: '请先勾选要删除的录音', icon: 'none' })
      return
    }
    wx.showModal({
      title: '批量删除',
      content: '将删除选中的 ' + ids.length + ' 条录音，删除后需重新录制，确认？',
      confirmColor: '#e53e3e',
      success: (r) => {
        if (!r.confirm) return
        queue.removeMany(ids)
        this.setData({ selectMode: false, selected: {}, selectedCount: 0 })
        this.refresh()
        wx.showToast({ title: '已删除 ' + ids.length + ' 条', icon: 'success' })
      }
    })
  },

  onUploadAll() {
    if (this.data.flushing) return
    this.setData({ flushing: true })
    queue
      .flush({ onItem: () => this.refresh() })
      .then((r) => {
        this.setData({ flushing: false })
        this.refresh()
        if (r.skipped) return
        wx.showToast({
          title: r.fail ? '成功' + r.ok + '，失败' + r.fail : '全部上传完成',
          icon: r.fail ? 'none' : 'success'
        })
      })
  },

  /** 本轮5 清理已完成/失效项（done + claimLost），释放本地空间 */
  onCleanup() {
    const n = queue.cleanup()
    this.refresh()
    wx.showToast({
      title: n ? '已清理 ' + n + ' 条' : '没有可清理项',
      icon: n ? 'success' : 'none'
    })
  }
})

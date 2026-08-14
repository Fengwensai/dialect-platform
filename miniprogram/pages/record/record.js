// 录音页：选任务/词条 → idle → recording → recorded → saved
const recorder = require('../../utils/recorder')
const wav = require('../../utils/wav')
const queue = require('../../utils/queue')
const api = require('../../utils/api')
const speaker = require('../../utils/speaker')
const { formatDuration, formatBytes } = require('../../utils/fmt')

const MAX_MS = 60000

function chipOf(w) {
  const st = w.status
  if (st === 'approved') return { cls: 'done', text: '已通过' }
  if (st === 'rejected') return { cls: 'reject', text: '需重录' }
  if (st === 'pending') return { cls: 'pending', text: '待审核' }
  return { cls: 'todo', text: '未录' }
}

Page({
  data: {
    state: 'idle', // idle | recording | recorded
    pickMode: false, // true = 先选任务/词条（首页进入）；false = 带参直接录音（词条页/队列页）
    taskLoading: false,
    taskOptions: [],
    taskIndex: -1,
    wordOptions: [],
    pickClaim: null, // 选中任务的领取统计（空池 CTA 用）
    taskId: '',
    wordId: '',
    content: '',
    pronunciation_hint: '',
    example_sentence: '',
    display: '0:00',
    wavPath: '',
    durationMs: 0,
    fileSizeText: '',
    saved: false
  },

  onLoad(options) {
    // 带参进入 = 上下文模式（词条页/队列页「重录」），先填信息再补提示
    if (options.taskId) {
      this.setData({
        taskId: String(options.taskId),
        wordId: String(options.wordId || ''),
        content: decodeURIComponent(options.content || ''),
        pickMode: false
      })
      this.loadWordContext()
    } else {
      // 首页「开始录音」进入：先选任务 → 再选词条
      this.setData({ pickMode: true })
      this.loadTasks()
    }
  },

  onUnload() {
    this.disableBackGuard()
    if (this.data.state === 'recording') {
      recorder.stopRecording().catch(() => {})
    }
    if (this._timer) clearInterval(this._timer)
    if (this._audio) {
      this._audio.stop()
      this._audio.destroy()
    }
  },

  // —— 任务/词条选择 ——
  loadTasks() {
    if (!speaker.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 600)
      return
    }
    this.setData({ taskLoading: true })
    api
      .request('/api/mp/tasks')
      .then((data) =>
        this.setData({ taskOptions: data.items || [], taskLoading: false })
      )
      .catch((err) => {
        this.setData({ taskLoading: false })
        wx.showToast({ title: (err && err.message) || '任务加载失败', icon: 'none' })
      })
  },

  onPickTask(e) {
    const idx = Number(e.currentTarget.dataset.index)
    const task = this.data.taskOptions[idx]
    if (!task) return
    this.setData({ taskIndex: idx, wordOptions: [], pickClaim: null })
    api
      .request('/api/mp/tasks/' + task.id + '/words')
      .then((data) => {
        const items = (data.items || []).map((w) => {
          const c = chipOf(w)
          return Object.assign({}, w, { chip: c.cls, chipText: c.text })
        })
        // 领取制：/words 只返回我领取的词条，没领时给出空池 CTA
        this.setData({ wordOptions: items, pickClaim: data.claim || null })
      })
      .catch((err) =>
        wx.showToast({ title: (err && err.message) || '词条加载失败', icon: 'none' })
      )
  },

  // 空池 CTA：去任务词条页领取后再回来录音
  goClaim(e) {
    const taskId = e.currentTarget.dataset.id
    if (!taskId) return
    wx.navigateTo({ url: '/pages/words/words?taskId=' + taskId })
  },

  onPickWord(e) {
    const idx = Number(e.currentTarget.dataset.index)
    const w = this.data.wordOptions[idx]
    const task = this.data.taskOptions[this.data.taskIndex]
    if (!w || !task) return
    this.setData({
      taskId: String(task.id),
      wordId: String(w.word_id),
      content: w.content,
      pronunciation_hint: w.pronunciation_hint || '',
      example_sentence: w.example_sentence || '',
      pickMode: false
    })
  },

  loadWordContext() {
    // 上下文进入：补发音提示/例句；失败不影响已带信息
    if (!this.data.taskId) return
    api
      .request('/api/mp/tasks/' + this.data.taskId + '/words')
      .then((data) => {
        const w = (data.items || []).find(
          (x) => String(x.word_id) === String(this.data.wordId)
        )
        if (!w) return
        this.setData({
          content: this.data.content || w.content,
          pronunciation_hint: w.pronunciation_hint || '',
          example_sentence: w.example_sentence || ''
        })
      })
      .catch(() => {})
  },

  enterPick() {
    this.disableBackGuard()
    this.setData({ pickMode: true, taskIndex: -1, wordOptions: [] })
    this.loadTasks()
  },

  // —— 录音 ——
  start() {
    if (this.data.state === 'recording') return
    this.setData({ state: 'recording', elapsed: 0, display: '0:00', saved: false })
    if (this._audio) this._audio.stop()
    this.enableBackGuard()

    this._t0 = Date.now()
    this._timer = setInterval(() => {
      const elapsed = Date.now() - this._t0
      if (elapsed >= MAX_MS) {
        this.stop()
        return
      }
      this.setData({ display: formatDuration(elapsed) })
    }, 200)

    recorder.startRecording().catch((err) => {
      clearInterval(this._timer)
      this._timer = null
      this.disableBackGuard()
      this.setData({ state: 'idle', display: '0:00' })
      const msg = (err && (err.errMsg || err.message)) || '未知错误'
      console.error('[record] 录音启动失败', err)
      // 权限被拒时引导去设置开启
      if (msg.indexOf('权限') !== -1) {
        wx.showModal({
          title: '需要麦克风权限',
          content: msg + '，是否前往设置开启？',
          confirmText: '去设置',
          success: (r) => {
            if (r.confirm) wx.openSetting()
          }
        })
        return
      }
      wx.showToast({
        title: '录音启动失败：' + msg,
        icon: 'none',
        duration: 3000
      })
    })
  },

  stop() {
    if (this.data.state !== 'recording') return
    clearInterval(this._timer)
    this._timer = null
    this.disableBackGuard()
    recorder
      .stopRecording()
      .then((res) => {
        if (!res || !res.pcmPath) {
          this.setData({ state: 'idle', display: '0:00' })
          return
        }
        return this._toWav(res)
      })
      .catch((err) => {
        this.setData({ state: 'idle', display: '0:00' })
        const msg = (err && (err.errMsg || err.message)) || '未知错误'
        console.error('[record] 录音失败', err)
        wx.showToast({ title: '录音失败：' + msg, icon: 'none', duration: 3000 })
      })
  },

  // PCM 临时文件 → WAV（补 44 字节小端头）
  _toWav(res) {
    const wavPath = queue.RECORDS_DIR + '/tmp_' + Date.now() + '.wav'
    return wav
      .pcmFileToWavFile({ pcmPath: res.pcmPath, wavPath })
      .then(() => {
        this.setData({
          state: 'recorded',
          wavPath,
          durationMs: res.durationMs,
          fileSizeText: formatBytes(res.fileSize),
          display: formatDuration(res.durationMs)
        })
      })
      .catch((err) => {
        this.setData({ state: 'idle', display: '0:00' })
        wx.showToast({
          title: '转 WAV 失败：' + ((err && err.message) || ''),
          icon: 'none',
          duration: 3000
        })
      })
  },

  // —— 试听 / 重录 / 保存 ——
  play() {
    if (!this.data.wavPath) return
    if (!this._audio) this._audio = wx.createInnerAudioContext()
    this._audio.stop()
    this._audio.src = this.data.wavPath
    this._audio.play()
  },

  retry() {
    this.disableBackGuard()
    if (this._audio) this._audio.stop()
    // 已保存的文件归队列所有，不删；未保存的临时文件清理掉
    if (!this.data.saved && this.data.wavPath) {
      try {
        wx.getFileSystemManager().unlinkSync(this.data.wavPath)
      } catch (e) {
        // 忽略
      }
    }
    this.setData({
      state: 'idle',
      wavPath: '',
      durationMs: 0,
      fileSizeText: '',
      display: '0:00',
      saved: false
    })
  },

  save() {
    const { taskId, wordId, content, wavPath, durationMs } = this.data
    if (!wavPath) return
    if (!/^[1-9]\d*$/.test(String(taskId))) {
      wx.showToast({ title: '请选择有效的任务', icon: 'none' })
      return
    }
    if (!/^[1-9]\d*$/.test(String(wordId))) {
      wx.showToast({ title: '请选择有效的词条', icon: 'none' })
      return
    }
    if (!content) {
      wx.showToast({ title: '请选择词条', icon: 'none' })
      return
    }
    this.disableBackGuard()
    queue.enqueue({ taskId, wordId, content, wavPath, durationMs })
    this.setData({ saved: true })
    wx.showToast({ title: '已存入本地队列', icon: 'success' })
  },

  // —— 离开确认（录音中退出会丢进度） ——
  enableBackGuard() {
    try {
      wx.enableAlertBeforeUnload({ message: '录音尚未完成，确定退出？' })
    } catch (e) {
      // 基础库过低时忽略
    }
  },
  disableBackGuard() {
    try {
      wx.disableAlertBeforeUnload()
    } catch (e) {
      // 忽略
    }
  }
})

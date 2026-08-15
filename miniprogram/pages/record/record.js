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
    saved: false,
    posIndex: 0, // 词条位置「第 x / y 条」（连续录音定位用）
    posTotal: 0,
    warn: false // ④ 最后 10 秒计时器变红提示
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
        // 缓存完整词条列表（含 status），供「保存后自动跳下一条」定位用
        this._wordList = data.items || []
        const items = this._wordList.map((w) => {
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
      posIndex: idx + 1,
      posTotal: this.data.wordOptions.length,
      pickMode: false
    })
  },

  loadWordContext() {
    // 上下文进入：补发音提示/例句；失败不影响已带信息
    if (!this.data.taskId) return
    api
      .request('/api/mp/tasks/' + this.data.taskId + '/words')
      .then((data) => {
        // 缓存完整词条列表（含 status），供「保存后自动跳下一条」定位用
        this._wordList = data.items || []
        const list = this._wordList
        const idx = list.findIndex((x) => String(x.word_id) === String(this.data.wordId))
        const w = idx >= 0 ? list[idx] : null
        if (!w) return
        this.setData({
          content: this.data.content || w.content,
          pronunciation_hint: w.pronunciation_hint || '',
          example_sentence: w.example_sentence || '',
          posIndex: idx + 1,
          posTotal: list.length
        })
      })
      .catch(() => {})
  },

  // —— 连续录音：保存后自动跳下一条未录词条 ——
  /**
   * 找同任务里「下一条还需要录」的词条（环绕：从当前往后，找不到绕回开头）。
   * 候选 = 后端 status 为 null/rejected，且不在本地队列的 pending/uploading/done。
   * 列表缺失时 fallback 重新拉接口；无候选返回 null。
   */
  _nextUnrecorded() {
    const taskId = this.data.taskId
    if (!taskId) return null

    // 本地队列已录集合（taskId:wordId），用于跳过已录/待传/传中的词条
    const queued = {}
    queue.list().forEach((it) => {
      if (it.status === 'pending' || it.status === 'uploading' || it.status === 'done') {
        queued[String(it.taskId) + ':' + String(it.wordId)] = true
      }
    })

    const list = this._wordList
    if (!list || !list.length) {
      // 列表没缓存到（如接口失败）：拉一次重建，仍拿不到就放弃自动跳
      api
        .request('/api/mp/tasks/' + taskId + '/words')
        .then((data) => {
          this._wordList = data.items || []
          const next = this._pickNext(queued)
          if (next) this._advanceTo(next)
        })
        .catch(() => {})
      return null
    }

    const next = this._pickNext(queued)
    if (next) this._advanceTo(next)
    return next
  },

  _pickNext(queued) {
    const list = this._wordList || []
    const taskId = String(this.data.taskId)
    const curId = String(this.data.wordId)

    const isCandidate = (w) => {
      // 已在本地队列（已录/待传/传中/完成）→ 跳过
      if (queued[taskId + ':' + String(w.word_id)]) return false
      // 后端 status：null=未录、rejected=需重录 是候选；approved/pending 跳过
      const st = w.status
      return st === null || st === undefined || st === 'rejected'
    }

    const n = list.length
    if (!n) return null

    // 当前词条在列表里 → 从其后往后扫，找不到绕回开头（环绕，漏录的也能续上）；
    // 当前词条不在列表（如重录一个已解绑词条）→ 直接从开头取第一个候选。
    const curIdx = list.findIndex((w) => String(w.word_id) === curId)
    if (curIdx < 0) {
      for (let i = 0; i < n; i++) {
        if (isCandidate(list[i])) return list[i]
      }
      return null
    }
    for (let step = 1; step <= n; step++) {
      const w = list[(curIdx + step) % n]
      if (isCandidate(w)) return w
    }
    return null
  },

  /** 跳到指定词条：更新信息并重置为待录音状态 */
  _advanceTo(next) {
    this.disableBackGuard()
    if (this._audio) {
      this._audio.stop()
      this._audio.destroy()
      this._audio = null
    }
    const list = this._wordList || []
    const idx = list.findIndex((w) => String(w.word_id) === String(next.word_id))
    this.setData({
      wordId: String(next.word_id),
      content: next.content,
      pronunciation_hint: next.pronunciation_hint || '',
      example_sentence: next.example_sentence || '',
      posIndex: idx >= 0 ? idx + 1 : 0,
      posTotal: list.length,
      state: 'idle',
      display: '0:00',
      wavPath: '',
      durationMs: 0,
      fileSizeText: '',
      saved: false,
      warn: false
    })
  },

  enterPick() {
    this.disableBackGuard()
    this.setData({ pickMode: true, taskIndex: -1, wordOptions: [] })
    this.loadTasks()
  },

  // —— 录音 ——
  start() {
    if (this.data.state === 'recording') return
    this.setData({ state: 'recording', elapsed: 0, display: '0:00', saved: false, warn: false })
    this._warned = false
    if (this._audio) this._audio.stop()
    this.enableBackGuard()

    this._t0 = Date.now()
    this._timer = setInterval(() => {
      const elapsed = Date.now() - this._t0
      if (elapsed >= MAX_MS) {
        this.stop()
        return
      }
      // ④ 最后 10 秒：计时器变红 + 一次性 toast 预告
      if (elapsed >= MAX_MS - 10000 && !this._warned) {
        this._warned = true
        this.setData({ warn: true })
        wx.showToast({ title: '最后 10 秒', icon: 'none' })
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
      saved: false,
      warn: false
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
    const id = queue.enqueue({ taskId, wordId, content, wavPath, durationMs })
    this.setData({ saved: true })

    // ③ 自动上传（默认开）：保存后立即传这一条，不打断连续录音；失败退回队列
    // （可一键上传/重试/下次保存兜底）。延迟 toast 让「已保存，继续下一条」先完整展示。
    if (queue.getAutoUpload()) {
      queue.uploadOne(id, { onItem: () => {} }).then((r) => {
        if (r && r.fail) {
          setTimeout(() => {
            wx.showToast({ title: '上传失败，已退回队列', icon: 'none', duration: 2000 })
          }, 1500)
        }
      })
    }

    // 连续录音：保存成功后自动跳同任务下一条未录词条（停在待录音状态，用户点「开始录音」）
    const hasList = !!(this._wordList && this._wordList.length)
    const next = this._nextUnrecorded()
    wx.showToast({
      // 列表缺失时（罕见，走 fallback 异步重建）用中性文案，避免误报「已全部录完」
      title: hasList ? (next ? '已保存，继续下一条' : '已保存，本任务已全部录完') : '已保存',
      icon: 'success'
    })
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

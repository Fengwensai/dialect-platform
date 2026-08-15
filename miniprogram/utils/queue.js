/**
 * 本地缓存队列（重点）。
 *
 * 双持久化：元数据 wx.setStorageSync('MP_RECORD_QUEUE')，音频文件存
 * USER_DATA_PATH/records/。上传默认「保存后自动」（我的页可关），失败/离线项
 * 回退到队列页/我的页「一键上传」；重录覆盖。
 *
 * 队列项结构：
 * { id, taskId, wordId, content, taskName, wavPath, durationMs, createdAt,
 *   status: 'pending'|'uploading'|'done'|'error'|'claimLost', error }
 * taskName：任务名（旧项可能为空，队列页回退显示 taskId）。
 * claimLost：上传被 403 拒绝（该词条未被领取/已被解绑），需先去任务页领取后再重录。
 */
const uploader = require('./uploader')

const QUEUE_KEY = 'MP_RECORD_QUEUE'
const AUTO_UPLOAD_KEY = 'MP_AUTO_UPLOAD'
const RECORDS_DIR = wx.env.USER_DATA_PATH + '/records'

let flushing = false // 防重入

function _load() {
  try {
    return wx.getStorageSync(QUEUE_KEY) || []
  } catch (e) {
    return []
  }
}

function _save(items) {
  wx.setStorageSync(QUEUE_KEY, items)
}

function _fileExists(p) {
  try {
    wx.getFileSystemManager().accessSync(p)
    return true
  } catch (e) {
    return false
  }
}

function _unlink(p) {
  try {
    wx.getFileSystemManager().unlinkSync(p)
  } catch (e) {
    // 文件不存在或已删，忽略
  }
}

function _genId() {
  return 'rec_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6)
}

/**
 * 入队。同 (taskId, wordId) 已有非 done 项 → 覆盖（重录），删除旧 wav 文件。
 * @param {object} item { taskId, wordId, content, wavPath, durationMs }
 * @returns {string} 队列项 id
 */
function enqueue(item) {
  // 统一转字符串，避免数字/字符串混存导致去重失效
  const taskId = String(item.taskId)
  const wordId = String(item.wordId)
  const items = _load()
  const dup = items.find(
    (x) => String(x.taskId) === taskId && String(x.wordId) === wordId && x.status !== 'done'
  )
  if (dup) {
    if (dup.wavPath && dup.wavPath !== item.wavPath) _unlink(dup.wavPath)
    Object.assign(dup, item, {
      id: dup.id,
      taskId,
      wordId,
      status: 'pending',
      error: '',
      createdAt: Date.now()
    })
    _save(items)
    return dup.id
  }
  const id = _genId()
  items.push(
    Object.assign(
      { id, taskId, wordId, status: 'pending', error: '', createdAt: Date.now() },
      item
    )
  )
  _save(items)
  return id
}

/** 全部队列项（元数据，含 wavPath） */
function list() {
  return _load()
}

/** 统计：total / pending / uploading / done / error / claimLost */
function count() {
  const items = _load()
  const c = { total: items.length, pending: 0, uploading: 0, done: 0, error: 0, claimLost: 0 }
  items.forEach((x) => {
    if (c[x.status] !== undefined) c[x.status]++
  })
  return c
}

function _update(id, patch) {
  const items = _load()
  const it = items.find((x) => x.id === id)
  if (it) {
    Object.assign(it, patch)
    _save(items)
  }
  return it
}

function markUploading(id) {
  return _update(id, { status: 'uploading' })
}

function markDone(id) {
  return _update(id, { status: 'done', error: '' })
}

function markError(id, msg) {
  return _update(id, { status: 'error', error: msg || '上传失败' })
}

/** 标记为「未领取/已解绑」：该词条已不可上传，需先去任务页领取后重录 */
function markClaimLost(id, msg) {
  return _update(id, {
    status: 'claimLost',
    error: msg || '该词条未领取或已被解绑，请先领取'
  })
}

/**
 * 上传单条：markUploading → uploadRecording → 成功 markDone+删本地文件 / 失败标错。
 * @param {object} item 队列项
 * @param {object} [opts] { onItem?(item, res, err) }
 * @returns {Promise<{ok:number, fail:number}>}
 */
function _uploadOne(item, opts) {
  markUploading(item.id)
  return uploader
    .uploadRecording(item)
    .then((res) => {
      markDone(item.id)
      if (item.wavPath) _unlink(item.wavPath)
      if (opts && opts.onItem) opts.onItem(item, res, null)
      return { ok: 1, fail: 0 }
    })
    .catch((err) => {
      if (err && err.claimLost) {
        markClaimLost(item.id, (err && err.message) || '该词条未被领取')
      } else {
        markError(item.id, (err && err.message) || String(err))
      }
      if (opts && opts.onItem) opts.onItem(item, null, err)
      return { ok: 0, fail: 1 }
    })
}

/**
 * 自动上传开关（③：保存后立即上传，默认开）。
 * 未设置过（getStorageSync 返回 ''）视为开；显式 setAutoUpload(false) 后才关。
 */
function getAutoUpload() {
  return wx.getStorageSync(AUTO_UPLOAD_KEY) !== false
}

function setAutoUpload(v) {
  wx.setStorageSync(AUTO_UPLOAD_KEY, !!v)
}

/**
 * 单条立即上传（③自动上传用）：保存后直接传这一条，不打断连续录音。
 * 只传 pending 项；正在批量上传（flushing）时跳过，留待下次触发（避免双传产生重复录音）。
 * @returns {Promise<{ok:number, fail:number, skipped?:boolean}>}
 */
function uploadOne(id, opts) {
  if (flushing) return Promise.resolve({ ok: 0, fail: 0, skipped: true })
  const it = _load().find((x) => x.id === id)
  if (!it || it.status !== 'pending') {
    return Promise.resolve({ ok: 0, fail: 0, skipped: true })
  }
  return _uploadOne(it, opts)
}

/**
 * 重试单条：把 error/claimLost 项改回 pending 并立即重新上传（不删本地文件、不用重录）。
 * @param {string} id 队列项 id
 * @param {object} [opts] { onItem?(item, res, err) }
 * @returns {Promise<{ok:number, fail:number, skipped?:boolean}>}
 */
function retry(id, opts) {
  if (flushing) return Promise.resolve({ ok: 0, fail: 0, skipped: true })
  const items = _load()
  const it = items.find((x) => x.id === id)
  if (!it || (it.status !== 'error' && it.status !== 'claimLost')) {
    return Promise.resolve({ ok: 0, fail: 0, skipped: true })
  }
  Object.assign(it, { status: 'pending', error: '' })
  _save(items)
  return _uploadOne(it, opts)
}

/** 删除一条（连带删本地 wav 文件） */
function remove(id) {
  let items = _load()
  const it = items.find((x) => x.id === id)
  if (it && it.wavPath) _unlink(it.wavPath)
  items = items.filter((x) => x.id !== id)
  _save(items)
}

/** 批量删除（连带删各自本地 wav 文件） */
function removeMany(ids) {
  if (!ids || !ids.length) return
  const set = new Set(ids)
  let items = _load()
  items.forEach((x) => {
    if (set.has(x.id) && x.wavPath) _unlink(x.wavPath)
  })
  items = items.filter((x) => !set.has(x.id))
  _save(items)
}

/** 清空已完成项（连带删文件，释放存储空间） */
function clearDone() {
  let items = _load()
  items.forEach((x) => {
    if (x.status === 'done' && x.wavPath) _unlink(x.wavPath)
  })
  items = items.filter((x) => x.status !== 'done')
  _save(items)
}

/**
 * 统计本地录音文件占用（本轮5）：只计 wav 仍存在的项（成功上传后已删的不计）。
 * @returns {{bytes:number, files:number}}
 */
function storageUsed() {
  const fs = wx.getFileSystemManager()
  let bytes = 0
  let files = 0
  _load().forEach((x) => {
    if (!x.wavPath) return
    try {
      const st = fs.statSync(x.wavPath)
      bytes += st.size || 0
      files++
    } catch (e) {
      // 文件已删（成功上传/重录覆盖），跳过
    }
  })
  return { bytes, files }
}

/**
 * 清理释放空间（本轮5）：删「已完成」与「未领取/失效」项及其本地文件。
 * 已完成文件本已删（只清元数据）；claimLost 的录音无法上传，删掉释放真空间。
 * pending/uploading/error 保留（录音还需要上传/重试）。
 * @returns {number} 清理条数
 */
function cleanup() {
  let items = _load()
  let removed = 0
  items.forEach((x) => {
    if (x.status === 'done' || x.status === 'claimLost') {
      if (x.wavPath) _unlink(x.wavPath)
      removed++
    }
  })
  items = items.filter((x) => x.status !== 'done' && x.status !== 'claimLost')
  _save(items)
  return removed
}

/**
 * 一键提交：顺序上传所有 pending，逐个成功即删本地文件。
 * 失败项保留并标记 error，不中断后续；正在上传时不重入。
 * @param {object} [opts] { onProgress?(percent, msg), onItem?(item, result, err) }
 * @returns {Promise<{ok:number, fail:number, skipped?:boolean}>}
 */
function flush(opts) {
  opts = opts || {}
  if (flushing) return Promise.resolve({ ok: 0, fail: 0, skipped: true })

  const pending = _load().filter((x) => x.status === 'pending')
  if (!pending.length) {
    if (opts.onProgress) opts.onProgress(100, '无待上传')
    return Promise.resolve({ ok: 0, fail: 0 })
  }

  flushing = true
  let ok = 0
  let fail = 0

  const run = (i) => {
    const item = pending[i]
    if (!item) {
      flushing = false
      if (opts.onProgress) opts.onProgress(100, '完成')
      return Promise.resolve({ ok, fail })
    }
    if (opts.onProgress) {
      opts.onProgress(
        Math.round((i / pending.length) * 100),
        '上传中 ' + (item.content || item.id)
      )
    }
    return _uploadOne(item, opts).then((r) => {
      ok += r.ok
      fail += r.fail
      return run(i + 1)
    })
  }

  return run(0)
}

/**
 * 初始化（App.onLaunch 调一次）：确保录音目录存在。
 * 上传完全手动（队列页/我的页「一键上传」），不注册任何自动补传。
 */
function init() {
  try {
    const fs = wx.getFileSystemManager()
    if (!_fileExists(RECORDS_DIR)) fs.mkdirSync(RECORDS_DIR, true)
  } catch (e) {
    // 目录创建失败不阻塞运行
  }
}

module.exports = {
  QUEUE_KEY,
  RECORDS_DIR,
  getAutoUpload,
  setAutoUpload,
  uploadOne,
  enqueue,
  list,
  count,
  markUploading,
  markDone,
  markError,
  markClaimLost,
  remove,
  removeMany,
  clearDone,
  storageUsed,
  cleanup,
  flush,
  retry,
  init
}

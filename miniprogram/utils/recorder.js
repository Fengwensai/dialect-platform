/**
 * RecorderManager 封装：强制 PCM 16kHz / 16bit / 单声道 / 最长 60s。
 *
 * 数据流：onStop 返回 .pcm 临时文件（裸 PCM，无文件头）→ wav.js 补头转 .wav。
 */
const wav = require('./wav')

const RECORDER_CONFIG = {
  duration: 60000, // 最长 1 分钟
  sampleRate: 16000, // 语音学分析常用 16kHz（PCM 16bit）
  numberOfChannels: 1, // 单声道
  encodeBitRate: 48000, // 16kHz 的合法范围是 32000~96000（超范围会启动失败）
  format: 'PCM', // 有效值 aac/mp3/wav/PCM —— 必须大写，小写 'pcm' 会导致 start() 失败
  frameSize: 1
}

const manager = wx.getRecorderManager()

// stop() / start() 的挂起回调
let _stopResolve = null
let _startReject = null

/** 取可读错误信息（微信 err 对象只有 errMsg，本地 Error 有 message） */
function _errMsg(err) {
  if (!err) return '未知错误'
  return err.errMsg || err.message || JSON.stringify(err)
}

manager.onStop((res) => {
  const r = _stopResolve
  _stopResolve = null
  if (r) {
    r({
      pcmPath: res.tempFilePath,
      durationMs: res.duration || 0,
      fileSize: res.fileSize || 0
    })
  }
})

manager.onError((err) => {
  console.error('[recorder] onError', err)
  // 录音中报错 → 拒绝 stop 的等待者；启动报错 → 拒绝 start 的等待者
  if (_stopResolve) {
    const r = _stopResolve
    _stopResolve = null
    r(err)
  } else if (_startReject) {
    const r = _startReject
    _startReject = null
    r(err)
  }
})

/**
 * 麦克风权限预检。
 * - 从未授权/未拒绝过：直接通过，真机首次调用录音 API 会自动弹授权框；
 * - 曾被拒绝：明确报错，引导去设置开启。
 */
function ensurePermission() {
  return new Promise((resolve, reject) => {
    wx.getSetting({
      success(res) {
        if (res.authSetting['scope.record'] === false) {
          reject(new Error('已拒绝麦克风权限，请在设置中开启'))
        } else {
          resolve()
        }
      },
      fail: (e) => reject(e)
    })
  })
}

/**
 * 开始录音。
 * @param {object} [overrides] 覆盖 RECORDER_CONFIG 的字段
 * @returns {Promise} 启动成功 resolve；权限拒绝/失败 reject(err)
 */
function startRecording(overrides) {
  return ensurePermission().then(
    () =>
      new Promise((resolve, reject) => {
        _startReject = reject
        manager.start(Object.assign({}, RECORDER_CONFIG, overrides || {}))
        // start 无回调，延迟一拍视为已启动（真实错误由 onError 捕获）
        setTimeout(() => {
          _startReject = null
          resolve()
        }, 150)
      })
  )
}

/**
 * 停止录音并拿到结果。
 * @returns {Promise<{pcmPath:string, durationMs:number, fileSize:number}>}
 *          resolve：成功停止；reject：录音出错（err.errMsg）
 */
function stopRecording() {
  return new Promise((resolve, reject) => {
    _stopResolve = resolve
    manager.stop()
    // 兜底：异常平台 5s 未回调则超时拒绝，避免页面永远卡在"录音中"
    setTimeout(() => {
      if (_stopResolve) {
        _stopResolve = null
        reject(new Error('停止录音超时'))
      }
    }, 5000)
  })
}

function onInterruptionBegin(cb) {
  manager.onInterruptionBegin(cb)
}

function onInterruptionEnd(cb) {
  manager.onInterruptionEnd(cb)
}

module.exports = {
  RECORDER_CONFIG,
  startRecording,
  stopRecording,
  onInterruptionBegin,
  onInterruptionEnd
}

/**
 * 上传适配层。
 *
 * 后端 /api/mp/recordings 已就绪（speakers/recordings 表），USE_MOCK = false
 * 走真实 wx.uploadFile。需要临时回到离线模拟时再置 true。队列逻辑与此层解耦，
 * 上层只依赖 uploadRecording(item) 的 Promise<{id,url}>。
 */
const config = require('./config')
const speaker = require('./speaker')

const USE_MOCK = false

/**
 * 上传一条录音。
 * @param {object} item 队列项 { id, taskId, wordId, content, wavPath, durationMs }
 * @returns {Promise<{id:string, url:string}>}
 */
function uploadRecording(item) {
  if (USE_MOCK) {
    return new Promise((resolve) => {
      console.log('[uploader:mock] 上传', item.id, item.content, item.wavPath)
      setTimeout(() => {
        const id = 'mock_' + item.id
        console.log('[uploader:mock] 完成', id)
        resolve({ id: id, url: '/mock/' + item.id + '.wav' })
      }, 800)
    })
  }

  return new Promise((resolve, reject) => {
    const formData = {
      task_id: String(item.taskId),
      word_id: String(item.wordId),
      duration: String(item.durationMs),
      device_id: speaker.getDeviceId()
    }
    const nickname = speaker.getNickname()
    if (nickname) formData.nickname = nickname
    const gender = speaker.getGender()
    if (gender) formData.gender = gender
    const ageBracket = speaker.getAgeBracket()
    if (ageBracket) formData.age_bracket = ageBracket

    // 已登录则带 token：后端优先按登录身份落库（无 token 时回退 device_id）
    const header = {}
    if (speaker.getToken()) header.Authorization = 'Bearer ' + speaker.getToken()

    wx.uploadFile({
      url: config.API_BASE + '/api/mp/recordings',
      filePath: item.wavPath,
      name: 'file',
      header,
      formData,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          let body = {}
          try {
            body = JSON.parse(res.data)
          } catch (e) {
            // 忽略解析失败，仅用状态码判定成功
          }
          resolve({ id: body.recording_id, url: body.audio_url })
        } else {
          let detail = ''
          try {
            detail = JSON.parse(res.data).detail
          } catch (e) {
            detail = res.data
          }
          const err = new Error(
            '上传失败 HTTP ' + res.statusCode + (detail ? ': ' + detail : '')
          )
          // 领取制：本地队列里未领取/已被解绑/他人已领的词条，上传会被 403 拒绝。
          // 打 claimLost 标记，让队列明确提示「先去领取」而不是当作普通失败反复重试。
          if (res.statusCode === 403 && String(detail).indexOf('未被你领取') >= 0) {
            err.claimLost = true
          }
          reject(err)
        }
      },
      fail: reject
    })
  })
}

module.exports = { uploadRecording, USE_MOCK }

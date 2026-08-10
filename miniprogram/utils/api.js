/**
 * 带 token 的接口请求封装（GET/POST 均可用）。
 * 401 先静默重登（wx.login 换新 token）并带新 token 重试一次；重登失败才清会话抛"请重新登录"。
 * 非 2xx 抛后端 detail。
 */
const config = require('./config')
const speaker = require('./speaker')

// 401 并发续期去重：多个请求同时 401（如冷启动多页并发）只发一次 wx.login，共享同一新 token
let renewing = null
function renewSession() {
  if (!renewing) {
    renewing = speaker.login().then(() => speaker.isLoggedIn(), () => false)
    renewing.then(() => {
      renewing = null // 无论成败都清缓存，下次 401 重新发起
    })
  }
  return renewing
}

function request(path, opts, retried) {
  opts = opts || {}
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + path,
      method: opts.method || 'GET',
      data: opts.data || undefined,
      header: Object.assign(
        { 'Content-Type': 'application/json' },
        opts.header || {},
        { Authorization: 'Bearer ' + speaker.getToken() }
      ),
      success: (res) => {
        if (res.statusCode === 401) {
          if (!retried) {
            // token 过期（JWT 720 分钟）：wx.login 一键静默续期后重放原请求（仅一次），
            // 避免采集者隔天打开小程序所有请求 401 被踢、录音中断。
            renewSession()
              .then((ok) => {
                if (!ok) throw new Error('重新登录失败')
                return request(path, opts, true)
              })
              .then(resolve)
              .catch(() => {
                speaker.clearToken()
                reject(
                  new Error((res.data && res.data.detail) || '登录已过期，请重新登录')
                )
              })
            return
          }
          speaker.clearToken()
          reject(new Error((res.data && res.data.detail) || '登录已过期，请重新登录'))
          return
        }
        // 协议守卫 403：协议升级后旧用户冷启动被拦，回登录页重新确认
        if (
          res.statusCode === 403 &&
          res.data &&
          res.data.detail &&
          String(res.data.detail).indexOf('请先同意') >= 0
        ) {
          wx.reLaunch({ url: '/pages/login/login' })
          reject(new Error(res.data.detail))
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject(
            new Error((res.data && res.data.detail) || ('请求失败 HTTP ' + res.statusCode))
          )
        }
      },
      fail: reject
    })
  })
}

module.exports = { request }

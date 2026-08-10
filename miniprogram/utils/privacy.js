/**
 * 微信隐私授权单例（阶段十·上线准备）。
 *
 * 全局唯一的 wx.onNeedPrivacyAuthorization 在 app.js onLaunch 注册一次（后注册会覆盖
 * 前注册，切勿在页面 onShow 重复注册）。页面通过 setPopupHandler 挂「展示回调」：
 * 隐私接口被触发时，微信回调本模块，本模块再通知当前页面的隐私弹窗组件弹出。
 *
 * 同意走官方按钮（open-type="agreePrivacyAuthorization"）自动回调，无需手动 resolve；
 * 拒绝需手动 resolve({event:'disagree'})。
 */

let _resolve = null // onNeedPrivacyAuthorization 传来的 resolve，同意/拒绝时回调
let _popupHandler = null // 当前挂载弹窗组件的 show 回调
let _inited = false

/** 注册全局隐私授权监听（app.js onLaunch 调用一次）。低版本基础库无此 API 时静默跳过。 */
function init() {
  if (_inited || typeof wx.onNeedPrivacyAuthorization !== 'function') return
  _inited = true
  wx.onNeedPrivacyAuthorization((resolve) => {
    _resolve = resolve
    if (_popupHandler) _popupHandler()
    // 无挂载弹窗：保留 resolve，页面可用 getResolve() 补弹
  })
}

/** 页面组件挂载时注册展示回调（收到授权需求时弹窗）。 */
function setPopupHandler(cb) {
  _popupHandler = cb
}

/** 取当前待处理的 resolve（无挂载弹窗时供页面补弹）。 */
function getResolve() {
  return _resolve
}

function clearResolve() {
  _resolve = null
}

/** 拒绝：手动回调 resolve({event:'disagree'})，原隐私接口走 fail。 */
function disagree() {
  const r = _resolve
  _resolve = null
  if (r) r({ event: 'disagree' })
}

/** 查询隐私授权状态（needAuthorization 等）。低版本/异常兜底为不要求授权。 */
function getPrivacySetting() {
  return new Promise((resolve) => {
    if (typeof wx.getPrivacySetting !== 'function') {
      resolve({ needAuthorization: false, privacyContractName: '' })
      return
    }
    wx.getPrivacySetting({
      success: (res) => resolve(res || { needAuthorization: false }),
      fail: () => resolve({ needAuthorization: false, privacyContractName: '' })
    })
  })
}

/**
 * 主动触发隐私授权（type="nickname" 输入框聚焦不自动触发监听，需手动调）。
 * 会走全局 onNeedPrivacyAuthorization → 弹窗。resolve 表示授权流程已放行。
 */
function requireAuthorize() {
  return new Promise((resolve, reject) => {
    if (typeof wx.requirePrivacyAuthorize !== 'function') {
      resolve()
      return
    }
    wx.requirePrivacyAuthorize({
      success: () => resolve(),
      fail: (err) => reject(err || new Error('隐私授权被拒绝'))
    })
  })
}

/** 打开微信官方《隐私保护指引》页面。 */
function openContract() {
  if (typeof wx.openPrivacyContract === 'function') {
    wx.openPrivacyContract({ fail: () => {} })
  }
}

module.exports = {
  init,
  setPopupHandler,
  getResolve,
  clearResolve,
  disagree,
  getPrivacySetting,
  requireAuthorize,
  openContract
}

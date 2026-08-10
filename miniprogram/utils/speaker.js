/**
 * 发音人身份。
 *
 * 本期用微信登录（wx.login → /api/mp/login 换 openid + token）；device_id 保留，
 * 作为登录与旧上传身份的绑定键（后端登录时自动统一，避免双行）。token/speaker
 * 持久化到本地，冷启动恢复会话。
 */
const config = require('./config')

const DEVICE_KEY = 'MP_DEVICE_ID'
const NICKNAME_KEY = 'MP_NICKNAME'
const TOKEN_KEY = 'MP_TOKEN'
const SPEAKER_KEY = 'MP_SPEAKER'
const GENDER_KEY = 'MP_GENDER'
const AGE_BRACKET_KEY = 'MP_AGE_BRACKET'

function _genId() {
  const t = Date.now().toString(36)
  const r = Math.random().toString(36).slice(2, 10)
  return 'dev_' + t + r
}

/** 稳定设备 ID（不存在则生成并持久化），用于与历史 device_id 录音身份绑定 */
function getDeviceId() {
  let id = ''
  try {
    id = wx.getStorageSync(DEVICE_KEY)
  } catch (e) {
    // 忽略读取异常，走生成
  }
  if (!id) {
    id = _genId()
    try {
      wx.setStorageSync(DEVICE_KEY, id)
    } catch (e) {
      // 存储失败时本次会话用临时 ID
    }
  }
  return id
}

/** 发音人昵称（无则返回 null） */
function getNickname() {
  try {
    return wx.getStorageSync(NICKNAME_KEY) || null
  } catch (e) {
    return null
  }
}

/** 发音人头像 URL（无则返回空串） */
function getAvatarUrl() {
  const sp = getSpeaker()
  return (sp && sp.avatar_url) || ''
}

/** 省份代码（属地，团队码绑定后由服务端返回） */
function getProvinceCode() {
  const sp = getSpeaker()
  return (sp && sp.province_code) || null
}

/** 城市代码（属地，团队码绑定后由服务端返回） */
function getCityCode() {
  const sp = getSpeaker()
  return (sp && sp.city_code) || null
}

/** 团队码（属地绑定凭据；空=未加入团队） */
function getTeamCode() {
  const sp = getSpeaker()
  return (sp && sp.team_code) || null
}

/** 已绑定团队（有省+市+团队码），才能看到/录制本地区任务 */
function isBound() {
  const sp = getSpeaker() || {}
  return !!(sp.province_code && sp.city_code && sp.team_code)
}

/** 发音人画像（无则返回 null） */
function getGender() {
  try {
    return wx.getStorageSync(GENDER_KEY) || null
  } catch (e) {
    return null
  }
}

function setGender(v) {
  try {
    if (v) wx.setStorageSync(GENDER_KEY, v)
    else wx.removeStorageSync(GENDER_KEY)
  } catch (e) {
    // 忽略
  }
}

function getAgeBracket() {
  try {
    return wx.getStorageSync(AGE_BRACKET_KEY) || null
  } catch (e) {
    return null
  }
}

function setAgeBracket(v) {
  try {
    if (v) wx.setStorageSync(AGE_BRACKET_KEY, v)
    else wx.removeStorageSync(AGE_BRACKET_KEY)
  } catch (e) {
    // 忽略
  }
}

// —— token / speaker 会话 ——
function getToken() {
  try {
    return wx.getStorageSync(TOKEN_KEY) || ''
  } catch (e) {
    return ''
  }
}

function setToken(token) {
  try {
    wx.setStorageSync(TOKEN_KEY, token)
  } catch (e) {
    // 忽略
  }
}

function clearToken() {
  try {
    wx.removeStorageSync(TOKEN_KEY)
    wx.removeStorageSync(SPEAKER_KEY)
  } catch (e) {
    // 忽略
  }
}

function getSpeaker() {
  try {
    return wx.getStorageSync(SPEAKER_KEY) || null
  } catch (e) {
    return null
  }
}

function setSpeaker(speaker) {
  try {
    wx.setStorageSync(SPEAKER_KEY, speaker)
  } catch (e) {
    // 忽略
  }
}

/** 已登录？ */
function isLoggedIn() {
  return !!getToken()
}

/**
 * 微信一键登录：wx.login 拿 code → 后端换 token + 建档。
 * @param {string} [nickname]   授权取到的昵称（无则用本地缓存/微信用户）
 * @param {string} [avatarUrl]  授权取到的头像 URL（无则不传）
 * @returns {Promise<object>} 完整登录载荷 { access_token, speaker, pending_agreements }
 */
function login(nickname, avatarUrl) {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (r) => {
        if (!r.code) {
          reject(new Error('wx.login 未返回 code'))
          return
        }
        wx.request({
          url: config.API_BASE + '/api/mp/login',
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
          data: {
            code: r.code,
            device_id: getDeviceId(),
            nickname: nickname || getNickname() || undefined,
            avatar_url: avatarUrl || undefined,
            gender: getGender() || undefined,
            age_bracket: getAgeBracket() || undefined
          },
          success: (res) => {
            if (res.statusCode === 200 && res.data && res.data.access_token) {
              setToken(res.data.access_token)
              setSpeaker(res.data.speaker)
              // 回同步服务端画像：换设备/重装后，旧画像仍能带到本地并随登录/上传续传
              const sp = res.data.speaker
              if (sp && sp.gender) setGender(sp.gender)
              if (sp && sp.age_bracket) setAgeBracket(sp.age_bracket)
              console.log('[speaker] 登录成功', res.data.speaker)
              resolve(res.data)
            } else {
              const detail =
                (res.data && res.data.detail) || ('登录失败 HTTP ' + res.statusCode)
              reject(new Error(detail))
            }
          },
          fail: reject
        })
      },
      fail: reject
    })
  })
}

/**
 * 三类协议最新版本（公开，登录前勾选/阅读用）。
 * @returns {Promise<Array<{type,title,version,content}>>}
 */
function getAgreements() {
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + '/api/mp/agreements',
      method: 'GET',
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data || [])
        } else {
          reject(
            new Error(
              (res.data && res.data.detail) || ('获取协议失败 HTTP ' + res.statusCode)
            )
          )
        }
      },
      fail: reject
    })
  })
}

/**
 * 我尚未同意最新版的协议 type 列表（Bearer；空 = 全部已同意）。
 * @returns {Promise<string[]>}
 */
function getPendingAgreements() {
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + '/api/mp/agreements/pending',
      method: 'GET',
      header: { Authorization: 'Bearer ' + getToken() },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve((res.data && res.data.pending_agreements) || [])
        } else {
          reject(
            new Error(
              (res.data && res.data.detail) ||
                ('获取待确认协议失败 HTTP ' + res.statusCode)
            )
          )
        }
      },
      fail: reject
    })
  })
}

/**
 * 提交协议同意（Bearer）。409 协议已更新时 err.message 为后端 detail。
 * @param {Array<{type:string, version:number}>} accepted
 * @returns {Promise<string[]>} 仍待确认的 type 列表（空 = 全部已同意）
 */
function acceptAgreements(accepted) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + '/api/mp/agreements/accept',
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + getToken()
      },
      data: { accepted: accepted || [] },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve((res.data && res.data.pending_agreements) || [])
        } else {
          reject(
            new Error(
              (res.data && res.data.detail) ||
                ('提交协议失败 HTTP ' + res.statusCode)
            )
          )
        }
      },
      fail: reject
    })
  })
}

/**
 * 加入团队：凭团队码绑定属地（省+市），绑定后锁定不可自改。
 * @param {string} code 团队码
 * @returns {Promise<object>} 更新后的 speaker
 */
function joinTeam(code) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + '/api/mp/team/join',
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + getToken()
      },
      data: { code: code || '' },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const updated = res.data // 端点直接返回 SpeakerOut
          setSpeaker(updated)
          if (updated.gender) setGender(updated.gender)
          if (updated.age_bracket) setAgeBracket(updated.age_bracket)
          resolve(updated)
        } else {
          const detail =
            (res.data && res.data.detail) || ('绑定失败 HTTP ' + res.statusCode)
          reject(new Error(detail))
        }
      },
      fail: reject
    })
  })
}

/**
 * 保存发音人画像（性别/年龄段）：先落本地，再同步服务端。
 * 未登录时仅本地保存；已登录走原生 wx.request（api.js 依赖本模块，反向 require 会有 CommonJS 环）。
 * @param {string|null} gender    male/female/other
 * @param {string|null} age_bracket under18/age18_30/age31_45/age46_60/over60
 * @returns {Promise<object>} 更新后的 speaker
 */
function setProfile(gender, age_bracket) {
  setGender(gender)
  setAgeBracket(age_bracket)
  const sp = getSpeaker() || {}
  sp.gender = gender || null
  sp.age_bracket = age_bracket || null
  setSpeaker(sp)
  if (!getToken()) return Promise.resolve(sp)
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + '/api/mp/profile',
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + getToken()
      },
      data: {
        gender: gender || undefined,
        age_bracket: age_bracket || undefined
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const updated = res.data || sp // 端点直接返回 SpeakerOut
          setSpeaker(updated)
          resolve(updated)
        } else {
          const detail =
            (res.data && res.data.detail) || ('保存失败 HTTP ' + res.statusCode)
          reject(new Error(detail))
        }
      },
      fail: reject
    })
  })
}

/**
 * 更新头像昵称：先落本地，再同步服务端。
 * @param {object} patch { nickname?, avatar_url? }（非空才提交）
 * @returns {Promise<object>} 更新后的 speaker
 * 属地（省/市）由团队码绑定决定，此处不允许自改。
 */
function updateProfile(patch) {
  patch = patch || {}
  const sp = getSpeaker() || {}
  if (patch.nickname) sp.nickname = patch.nickname
  if (patch.avatar_url !== undefined) sp.avatar_url = patch.avatar_url || null
  setSpeaker(sp)
  if (!getToken()) return Promise.resolve(sp)
  const data = {}
  if (patch.nickname) data.nickname = patch.nickname
  if (patch.avatar_url) data.avatar_url = patch.avatar_url
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + '/api/mp/profile',
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + getToken()
      },
      data,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const updated = res.data || sp // 端点直接返回 SpeakerOut
          setSpeaker(updated)
          if (updated.gender) setGender(updated.gender)
          if (updated.age_bracket) setAgeBracket(updated.age_bracket)
          resolve(updated)
        } else {
          const detail =
            (res.data && res.data.detail) || ('保存失败 HTTP ' + res.statusCode)
          reject(new Error(detail))
        }
      },
      fail: reject
    })
  })
}

/** 头像展示地址：/media 开头拼 API_BASE，本地临时/完整 URL 原样返回 */
function getAvatarDisplayUrl() {
  const u = getAvatarUrl()
  if (!u) return ''
  if (u.indexOf('/media/') === 0) return config.API_BASE + u
  return u
}

/** 是否为服务器头像 URL（/media/ 相对路径，或 https:// 完整地址）；本地临时路径需先上传 */
function isServerAvatar(u) {
  return u.indexOf('/media/') === 0 || u.indexOf('https://') === 0
}

/**
 * 上传头像到服务器：chooseAvatar 的本地临时路径对其它设备无效，上传后
 * 服务器返回 /media/avatars/... 路径并更新发音人。
 * @param {string} localPath 本地临时头像路径
 * @returns {Promise<object>} 更新后的 speaker
 */
function uploadAvatar(localPath) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: config.API_BASE + '/api/mp/avatar',
      filePath: localPath,
      name: 'file',
      header: { Authorization: 'Bearer ' + getToken() },
      success: (res) => {
        let data
        try {
          data = JSON.parse(res.data)
        } catch (e) {
          reject(new Error('头像上传响应解析失败'))
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          setSpeaker(data) // 端点直接返回 SpeakerOut
          resolve(data)
        } else {
          reject(new Error((data && data.detail) || ('头像上传失败 HTTP ' + res.statusCode)))
        }
      },
      fail: reject
    })
  })
}

/**
 * 把头像转成服务器 URL：已是服务器 URL 原样返回；本地临时路径先上传再返回服务器路径。
 * @param {string} path
 * @returns {Promise<string|null>}
 */
function ensureAvatarUrl(path) {
  if (!path) return Promise.resolve(null)
  if (isServerAvatar(path)) return Promise.resolve(path)
  return uploadAvatar(path).then((sp) => (sp && sp.avatar_url) || null)
}

module.exports = {
  API_BASE: config.API_BASE,
  getDeviceId,
  getNickname,
  getAvatarUrl,
  getAvatarDisplayUrl,
  getProvinceCode,
  getCityCode,
  getTeamCode,
  isBound,
  getGender,
  getAgeBracket,
  setProfile,
  updateProfile,
  joinTeam,
  uploadAvatar,
  ensureAvatarUrl,
  getToken,
  setToken,
  clearToken,
  getSpeaker,
  setSpeaker,
  isLoggedIn,
  login,
  getAgreements,
  getPendingAgreements,
  acceptAgreements,
  DEVICE_KEY,
  NICKNAME_KEY,
  TOKEN_KEY,
  SPEAKER_KEY,
  GENDER_KEY,
  AGE_BRACKET_KEY
}

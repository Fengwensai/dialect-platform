// 我的：个人中心（头像昵称 / 方言点 / 画像）+ 常用功能卡片（录音队列 / 一键上传 / 审核进度 / 使用说明 / 导出录音时长）
const config = require('../../utils/config')
const api = require('../../utils/api')
const queue = require('../../utils/queue')
const region = require('../../utils/region')
const speaker = require('../../utils/speaker')

function formatDuration(ms) {
  if (!ms || ms <= 0) return '0 秒'
  const totalSec = Math.round(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m ? `${m} 分 ${s} 秒` : `${s} 秒`
}

const GENDER_OPTIONS = ['男', '女', '其他']
const GENDER_CODES = ['male', 'female', 'other']
const AGE_OPTIONS = ['<18', '18-30', '31-45', '46-60', '>60']
const AGE_CODES = ['under18', 'age18_30', 'age31_45', 'age46_60', 'over60']

Page({
  data: {
    loggedIn: false, // 是否已登录（先浏览后登录整改：未登录也可进本页浏览，登录由用户主动触发）
    nickname: '',
    displayAvatarUrl: '', // 头像展示地址（/media 自动拼 API_BASE）
    provinceName: '',
    profileText: '', // 性别 · 年龄段 摘要（未填为空）
    // 常用功能
    stats: { total: 0, pending: 0, uploading: 0, done: 0, error: 0 },
    autoUpload: true, // 保存后自动上传（③，默认开，queue.getAutoUpload 同步）
    flushing: false,
    progress: 0,
    progressText: '',
    reviewProgress: null, // 审核进度（跨任务按状态汇总）
    exporting: false // 导出录音时长中
  },

  onShow() {
    // 先浏览后登录（审核整改）：未登录不强制跳登录页，本页可浏览常用功能，仅个人数据/接口延迟到登录
    if (!speaker.isLoggedIn()) {
      this.setData({
        loggedIn: false,
        nickname: '',
        displayAvatarUrl: '',
        provinceName: '',
        profileText: ''
      })
      this.refreshStats() // 录音队列是本地数据，未登录也可看
      this.setData({ autoUpload: queue.getAutoUpload() })
      return
    }
    this.setData({ loggedIn: true })
    this.refreshUser()
    this.loadProvince()
    this.refreshStats()
    this.setData({ autoUpload: queue.getAutoUpload() })
    this.loadProgress().catch(() => {}) // 进页静默拉一次；失败不阻塞页面
  },

  /** 去登录页（用户主动触发） */
  goLogin() {
    wx.navigateTo({ url: '/pages/login/login' })
  },

  /** ③ 保存后自动上传开关（本地功能，未登录也可用） */
  onToggleAutoUpload(e) {
    queue.setAutoUpload(e.detail.value)
  },

  onPullDownRefresh() {
    this.refreshStats()
    this.loadProgress()
      .catch(() => {})
      .then(() => wx.stopPullDownRefresh())
  },

  refreshStats() {
    this.setData({ stats: queue.count() })
  },

  /** 拉取审核进度；失败向调用方抛错（由调用方决定提示） */
  loadProgress() {
    return api
      .request('/api/mp/progress')
      .then((p) => this.setData({ reviewProgress: p }))
  },

  goQueue() {
    // 录音队列是本地数据，未登录也可浏览
    wx.navigateTo({ url: '/pages/queue/queue' })
  },

  onUploadAll() {
    if (!speaker.isLoggedIn()) return this.goLogin()
    if (this.data.flushing) return
    if (this.data.stats.pending === 0) {
      wx.showToast({ title: '没有待上传的录音', icon: 'none' })
      return
    }
    this.setData({ flushing: true, progress: 0, progressText: '开始上传' })
    queue
      .flush({
        onProgress: (p, msg) => this.setData({ progress: p, progressText: msg }),
        onItem: () => this.refreshStats()
      })
      .then((r) => {
        this.setData({ flushing: false })
        this.refreshStats()
        if (r.skipped) return
        wx.showToast({
          title: r.fail ? '成功' + r.ok + '，失败' + r.fail : '全部上传完成',
          icon: r.fail ? 'none' : 'success'
        })
      })
  },

  goProgress() {
    if (!speaker.isLoggedIn()) return this.goLogin()
    wx.navigateTo({ url: '/pages/progress/progress' })
  },

  /** 导出录音时长：先拉统计预览，确认后下载 CSV 并分享/保存 */
  onExportDuration() {
    if (!speaker.isLoggedIn()) return this.goLogin()
    if (this.data.exporting) return
    api
      .request('/api/mp/me/durations')
      .then((d) => this.confirmExport(d))
      .catch(() => this.confirmExport(null)) // 统计失败也能导出
  },

  confirmExport(d) {
    const content = d
      ? `共 ${d.total_count} 条录音 · 总时长 ${formatDuration(d.total_duration_ms)}\n有效（已通过）${d.approved_count} 条 · ${formatDuration(d.approved_duration_ms)}\n待审核 ${d.pending_count} 条 · 需重录 ${d.rejected_count} 条`
      : '将我的录音时长明细导出为 CSV 文件（含每条录音的状态与时长），可发送到文件传输助手保存。'
    wx.showModal({
      title: '导出录音时长',
      content,
      confirmText: '导出',
      cancelText: '取消',
      success: (r) => {
        if (r.confirm) this.doExportDuration()
      }
    })
  },

  doExportDuration() {
    this.setData({ exporting: true })
    wx.downloadFile({
      url: config.API_BASE + '/api/mp/me/export',
      header: { Authorization: 'Bearer ' + speaker.getToken() },
      success: (res) => {
        if (res.statusCode !== 200) {
          wx.showToast({ title: '导出失败（HTTP ' + res.statusCode + '）', icon: 'none' })
          return
        }
        this.shareCsv(res.tempFilePath)
      },
      fail: () => {
        wx.showToast({ title: '导出失败，请检查网络', icon: 'none' })
      },
      complete: () => this.setData({ exporting: false })
    })
  },

  shareCsv(tempPath) {
    // 先存为本地文件拿到稳定路径再分享；存储失败则用临时路径兜底
    wx.saveFile({
      tempFilePath: tempPath,
      success: (s) => this.shareFile(s.savedFilePath),
      fail: () => this.shareFile(tempPath)
    })
  },

  shareFile(filePath) {
    const fileName = '我的录音时长.csv'
    if (wx.shareFileMessage) {
      wx.shareFileMessage({
        filePath,
        fileName,
        success: () => {
          wx.showToast({ title: '已导出，可发送到文件传输助手保存', icon: 'none' })
        },
        fail: () => {
          wx.showModal({
            title: '导出完成',
            content: 'CSV 文件已生成。可再次点击导出，在分享面板中发送到「文件传输助手」保存到电脑。',
            showCancel: false
          })
        }
      })
    } else {
      wx.showModal({
        title: '导出完成',
        content: '当前微信版本暂不支持文件分享，请在开发者工具联调环境查看。',
        showCancel: false
      })
    }
  },

  onShowHelp() {
    wx.showModal({
      title: '使用说明',
      content:
        '1. 首页点「领取任务」选词条，用家乡话朗读（最长 60 秒，自动停止）\n2. 录音后可试听、重录，满意再「保存入队」\n3. 录音保存后自动上传（可在「我的」关闭）；失败项在「录音队列」点「重试」\n4. 后台审核后，「审核进度」显示 已通过 / 待审核 / 需重录',
      showCancel: false
    })
  },

  refreshUser() {
    const sp = speaker.getSpeaker() || {}
    const g = sp.gender || speaker.getGender()
    const a = sp.age_bracket || speaker.getAgeBracket()
    const gi = GENDER_CODES.indexOf(g)
    const ai = AGE_CODES.indexOf(a)
    const parts = []
    if (gi >= 0) parts.push(GENDER_OPTIONS[gi])
    if (ai >= 0) parts.push(AGE_OPTIONS[ai])
    this.setData({
      nickname: sp.nickname || '微信用户',
      displayAvatarUrl: speaker.getAvatarDisplayUrl(),
      profileText: parts.join(' · ')
    })
  },

  goProfile() {
    if (!speaker.isLoggedIn()) return this.goLogin()
    wx.navigateTo({ url: '/pages/profile/profile' })
  },

  loadProvince() {
    const sp = speaker.getSpeaker() || {}
    if (!sp.province_code) {
      this.setData({ provinceName: '' })
      return
    }
    // 属地=团队码绑定的省+市，展示「省·市」
    region
      .regionText(sp.province_code, sp.city_code || '')
      .then((t) => this.setData({ provinceName: t }))
      .catch(() => this.setData({ provinceName: sp.province_code }))
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需重新微信授权登录，确认？',
      success: (r) => {
        if (r.confirm) {
          speaker.clearToken()
          wx.reLaunch({ url: '/pages/login/login' })
        }
      }
    })
  }
})

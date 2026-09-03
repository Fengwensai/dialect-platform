// 首页（录音台·精简版）：欢迎语 + 领取任务/开始录音两大入口，其余功能在「我的」页
const speaker = require('../../utils/speaker')

const share = require('../../utils/share')

Page({
  // 转发 + 朋友圈（右上角「…」）：本页未登录可浏览，两者都开（朋友圈落地当前页安全）
  onShareAppMessage: share.onShareAppMessage,
  onShareTimeline: share.onShareTimeline,
  data: {
    loggedIn: false, // 是否已登录（微信违规整改：未登录也可浏览首页，登录由用户主动触发）
    speakerName: '',
    bound: false, // 是否已加入团队（绑定属地）
    bindVisible: false, // 绑定团队弹窗
    bindInputFocus: false,
    teamCode: '',
    binding: false // 绑定请求中
  },

  onShow() {
    // 先浏览后登录（审核整改）：未登录不再强制跳登录页，留在首页可浏览功能入口
    if (!speaker.isLoggedIn()) {
      this.setData({ loggedIn: false, speakerName: '', bound: false, bindVisible: false })
      return
    }
    this.setData({ loggedIn: true })
    this.refreshSpeaker()
  },

  refreshSpeaker() {
    const sp = speaker.getSpeaker()
    this.setData({
      speakerName: (sp && sp.nickname) || '',
      bound: speaker.isBound()
    })
  },

  /** 去登录页（用户主动触发；登录后 switchTab 回首页） */
  goLogin() {
    wx.navigateTo({ url: '/pages/login/login' })
  },

  /** 首页未绑定门禁：横幅点「绑定团队」→ 弹自定义输入框（未登录先登录） */
  onBindTeam() {
    if (this.data.binding) return
    if (!speaker.isLoggedIn()) return this.goLogin()
    this.setData({ bindVisible: true, teamCode: '', bindInputFocus: false })
  },

  noop() {},

  closeBind() {
    if (this.data.binding) return
    this.setData({ bindVisible: false })
  },

  onBindInputFocus() {
    this.setData({ bindInputFocus: true })
  },

  onBindInputBlur() {
    this.setData({ bindInputFocus: false })
  },

  onTeamCodeInput(e) {
    // 团队码统一转大写，与后端存储一致
    this.setData({ teamCode: (e.detail.value || '').toUpperCase() })
  },

  /** 弹窗内「绑定」：校验 → joinTeam → 刷新 */
  doBind() {
    if (this.data.binding) return
    const code = (this.data.teamCode || '').trim()
    if (!code) {
      wx.showToast({ title: '请输入团队码', icon: 'none' })
      return
    }
    this.setData({ binding: true })
    speaker
      .joinTeam(code)
      .then(() => {
        this.setData({ bindVisible: false, binding: false })
        this.refreshSpeaker()
        wx.showToast({ title: '绑定成功', icon: 'success' })
      })
      .catch((err) => {
        this.setData({ binding: false })
        // 错误信息较长（如「已绑定团队，无法更换」），用弹窗完整展示
        wx.showModal({
          title: '绑定失败',
          content: (err && err.message) || '请检查团队码是否正确',
          showCancel: false
        })
      })
  },

  goRecord() {
    if (!speaker.isLoggedIn()) return this.goLogin()
    wx.navigateTo({ url: '/pages/record/record' })
  },

  goTasks() {
    if (!speaker.isLoggedIn()) return this.goLogin()
    wx.navigateTo({ url: '/pages/tasks/tasks' })
  }
})

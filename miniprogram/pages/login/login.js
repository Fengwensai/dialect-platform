// 登录页：协议勾选确认 → 微信登录门禁 → 完善资料（团队码必填 + 头像昵称性别年龄段可选）→ 进入首页
const speaker = require('../../utils/speaker')

const GENDER_OPTIONS = ['男', '女', '其他']
const GENDER_CODES = ['male', 'female', 'other']
const AGE_OPTIONS = ['<18', '18-30', '31-45', '46-60', '>60']
const AGE_CODES = ['under18', 'age18_30', 'age31_45', 'age46_60', 'over60']

Page({
  data: {
    loading: false,
    saving: false,
    authed: false, // 登录成功且未绑定团队，进入绑定+完善资料步骤
    teamCode: '', // 团队码（必填；绑定后属地=团队对应省市）
    avatarUrl: '',
    nickname: '',
    genderOptions: GENDER_OPTIONS,
    ageOptions: AGE_OPTIONS,
    genderIndex: -1,
    ageIndex: -1,
    // 协议三勾选
    agreements: [], // 三类协议最新版本（登录前勾选用）
    agreeLoading: false, // 协议列表拉取中
    agreeLoadError: false, // 协议列表拉取失败（避免空白卡死登录）
    checked: {}, // type → bool
    allChecked: false,
    // 登录后/版本升级的协议确认弹窗
    agreeVisible: false,
    agreeItems: [], // [{type, title, version}] 待确认
    agreeLoading: false
  },

  onLoad() {
    this._loadAgreements()
    if (speaker.isLoggedIn()) {
      // 已登录（协议升级后被 403 踢回 / 冷启动恢复）：查待确认协议
      this._checkPendingAfterUpgrade()
    }
  },

  noop() {},

  // 昵称输入聚焦不自动触发隐私监听，需主动触发隐私授权弹窗
  onNicknameFocus() {
    require('../../utils/privacy').requireAuthorize().catch(() => {})
  },

  // —— 协议 ——
  _loadAgreements() {
    this.setData({ agreeLoading: true, agreeLoadError: false })
    speaker
      .getAgreements()
      .then((list) => {
        this.setData({ agreements: list || [], agreeLoading: false })
      })
      .catch(() => {
        // 拉取失败：明确提示 + 可重试，避免协议列表空白导致登录按钮永远置灰（无路可走）
        this.setData({ agreeLoading: false, agreeLoadError: true })
      })
  },

  onReloadAgreements() {
    this._loadAgreements()
  },

  _checkPendingAfterUpgrade() {
    Promise.all([speaker.getAgreements(), speaker.getPendingAgreements()])
      .then(([agreements, pending]) => {
        if (pending && pending.length) {
          this._showAgreeModalFor(pending)
        } else {
          wx.switchTab({ url: '/pages/index/index' })
        }
      })
      .catch(() => {
        // 网络异常时 fail-open：先进首页（后端守卫本身也是空表放行）
        wx.switchTab({ url: '/pages/index/index' })
      })
  },

  _showAgreeModalFor(pending) {
    if ((this.data.agreements || []).length) {
      this._showAgreeModal(this.data.agreements, pending)
      return
    }
    speaker
      .getAgreements()
      .then((agreements) => this._showAgreeModal(agreements, pending))
      .catch(() => {})
  },

  _showAgreeModal(agreements, pending) {
    const items = (agreements || [])
      .filter((a) => pending.indexOf(a.type) >= 0)
      .map((a) => ({ type: a.type, title: a.title, version: a.version }))
    this.setData({ agreeItems: items, agreeVisible: true })
  },

  // 整行可点手动维护勾选态：自定义勾选框，不依赖原生 checkbox-group 内部状态同步
  onRowTap(e) {
    const type = e.currentTarget.dataset.type
    const checked = Object.assign({}, this.data.checked)
    checked[type] = !checked[type]
    const count = (this.data.agreements || []).length
    const checkedCount = Object.keys(checked).filter((k) => checked[k]).length
    this.setData({
      checked,
      // 协议未加载时 count=0：allChecked 恒 false，登录按钮不可点（避免假通过）
      allChecked: count > 0 && checkedCount === count
    })
  },

  onAgreementTap(e) {
    const type = e.currentTarget.dataset.type
    wx.navigateTo({ url: '/pages/agreement/agreement?type=' + type })
  },

  onAgreeItemTap(e) {
    const type = e.currentTarget.dataset.type
    wx.navigateTo({ url: '/pages/agreement/agreement?type=' + type })
  },

  onAgreeCancel() {
    if (this.data.agreeLoading) return
    this.setData({ agreeVisible: false })
  },

  onAgreeConfirm() {
    if (this.data.agreeLoading) return
    const items = this.data.agreeItems || []
    if (!items.length) {
      this.setData({ agreeVisible: false })
      return
    }
    const accepted = items.map((it) => ({ type: it.type, version: it.version }))
    this.setData({ agreeLoading: true })
    speaker
      .acceptAgreements(accepted)
      .then((pending) => {
        this.setData({ agreeLoading: false, agreeVisible: false })
        if (pending && pending.length) {
          // 部分仍待确认（理论不会走到——提交的都是最新版本）
          this._showAgreeModal(this.data.agreements, pending)
          return
        }
        if (speaker.isBound()) {
          this.enterHome()
        } else {
          this.setData({ authed: true })
        }
      })
      .catch((err) => {
        this.setData({ agreeLoading: false })
        const msg = (err && err.message) || ''
        if (msg.indexOf('协议已更新') >= 0) {
          wx.showToast({ title: '协议已更新，请重新阅读', icon: 'none' })
          // 重新拉取最新协议 + 待确认列表，保持弹窗
          Promise.all([speaker.getAgreements(), speaker.getPendingAgreements()])
            .then(([agreements, pending]) => {
              this._showAgreeModal(agreements, pending)
            })
            .catch(() => {})
        } else {
          wx.showToast({ title: '提交失败：' + msg, icon: 'none' })
        }
      })
  },

  // —— 登录 ——
  onLogin() {
    if (this.data.loading) return
    if (!this.data.allChecked) {
      wx.showToast({ title: '请先勾选并阅读同意全部协议', icon: 'none' })
      return
    }
    this.setData({ loading: true })
    wx.showLoading({ title: '登录中…', mask: true })
    // 微信登录：wx.login 静默换 token。
    // 注意：wx.getUserProfile 自 2022 年受微信隐私政策限制，无法稳定返回真实昵称/头像，
    // 因此昵称头像改用官方「头像昵称填写」能力在下一步采集（chooseAvatar + type=nickname）。
    speaker
      .login()
      .then((payload) => {
        wx.hideLoading()
        this.setData({ loading: false })
        const pending = (payload && payload.pending_agreements) || []
        if (pending.length) {
          // 有待确认协议：弹确认窗，同意后才能继续
          this._showAgreeModalFor(pending)
          return
        }
        // 已绑定团队（老用户换设备重登）直接进首页；否则进入绑定+完善资料步骤
        if (speaker.isBound()) {
          this.enterHome()
        } else {
          this.setData({ authed: true })
        }
      })
      .catch((err) => {
        wx.hideLoading()
        this.setData({ loading: false })
        wx.showToast({
          title: '登录失败：' + ((err && err.message) || ''),
          icon: 'none'
        })
      })
  },

  onChooseAvatar(e) {
    this.setData({ avatarUrl: e.detail.avatarUrl })
  },

  onNicknameInput(e) {
    this.setData({ nickname: e.detail.value })
  },

  onGenderChange(e) {
    this.setData({ genderIndex: Number(e.detail.value) })
  },

  onAgeChange(e) {
    this.setData({ ageIndex: Number(e.detail.value) })
  },

  onTeamCodeInput(e) {
    this.setData({ teamCode: e.detail.value })
  },

  saveProfile() {
    if (this.data.saving) return
    // 团队码必填：未绑定则必须先绑定（属地=团队对应省市）
    const code = (this.data.teamCode || '').trim()
    if (!speaker.isBound() && !code) {
      wx.showToast({ title: '请先填写团队码', icon: 'none' })
      return
    }
    this.setData({ saving: true })
    wx.showLoading({ title: '保存中…', mask: true })
    const bind = speaker.isBound() ? Promise.resolve() : speaker.joinTeam(code)
    // 画像（性别/年龄段）与头像昵称分开落库：setProfile 处理画像，updateProfile 处理头像昵称
    const g = this.data.genderIndex >= 0 ? GENDER_CODES[this.data.genderIndex] : null
    const a = this.data.ageIndex >= 0 ? AGE_CODES[this.data.ageIndex] : null
    Promise.all([bind, speaker.setProfile(g, a), this._saveAvatarNickname()])
      .then(() => {
        wx.hideLoading()
        this.setData({ saving: false })
        this.enterHome()
      })
      .catch((err) => {
        wx.hideLoading()
        this.setData({ saving: false })
        wx.showToast({
          title: '保存失败：' + ((err && err.message) || ''),
          icon: 'none'
        })
      })
  },

  async _saveAvatarNickname() {
    // 头像仅本地缓存展示（隐私指引声明：不存储于服务器）；昵称提交服务器供后台识别发音人
    await speaker.saveLocalAvatar(this.data.avatarUrl)
    const patch = {}
    if (this.data.nickname) patch.nickname = this.data.nickname
    return Object.keys(patch).length ? speaker.updateProfile(patch) : Promise.resolve()
  },

  skipProfile() {
    this.enterHome()
  },

  enterHome() {
    wx.switchTab({ url: '/pages/index/index' })
  }
})

// 个人信息编辑页：头像 / 姓名 / 属地（只读）/ 性别 / 年龄段
const region = require('../../utils/region')
const speaker = require('../../utils/speaker')

const GENDER_OPTIONS = ['男', '女', '其他']
const GENDER_CODES = ['male', 'female', 'other']
const AGE_OPTIONS = ['<18', '18-30', '31-45', '46-60', '>60']
const AGE_CODES = ['under18', 'age18_30', 'age31_45', 'age46_60', 'over60']

Page({
  data: {
    avatarUrl: '', // 原始值（服务器 /media/... 或刚选的本地临时路径），用于保存
    displayAvatarUrl: '', // 展示地址
    nickname: '',
    regionText: '', // 属地（省·市），只读展示
    genderOptions: GENDER_OPTIONS,
    genderCodes: GENDER_CODES,
    ageOptions: AGE_OPTIONS,
    ageCodes: AGE_CODES,
    genderIndex: -1,
    ageIndex: -1,
    saving: false
  },

  onLoad() {
    const sp = speaker.getSpeaker() || {}
    this.setData({
      nickname: sp.nickname || '微信用户',
      avatarUrl: speaker.getAvatarUrl(), // 本地缓存头像（不上传服务器）
      displayAvatarUrl: speaker.getAvatarDisplayUrl(),
      genderIndex: GENDER_CODES.indexOf(sp.gender || ''),
      ageIndex: AGE_CODES.indexOf(sp.age_bracket || '')
    })
    // 属地由团队码绑定决定，只读展示（省·市）
    if (sp.province_code) {
      region
        .regionText(sp.province_code, sp.city_code || '')
        .then((t) => this.setData({ regionText: t }))
        .catch(() => {})
    }
  },

  onChooseAvatar(e) {
    const p = e.detail.avatarUrl
    this.setData({ avatarUrl: p, displayAvatarUrl: p })
  },

  onNicknameInput(e) {
    this.setData({ nickname: e.detail.value })
  },

  // 昵称输入聚焦不自动触发隐私监听，需主动触发隐私授权弹窗
  onNicknameFocus() {
    require('../../utils/privacy').requireAuthorize().catch(() => {})
  },

  onGenderChange(e) {
    this.setData({ genderIndex: Number(e.detail.value) })
  },

  onAgeChange(e) {
    this.setData({ ageIndex: Number(e.detail.value) })
  },

  save() {
    if (this.data.saving) return
    this.setData({ saving: true })
    wx.showLoading({ title: '保存中…', mask: true })
    const g = this.data.genderIndex >= 0 ? GENDER_CODES[this.data.genderIndex] : null
    const a = this.data.ageIndex >= 0 ? AGE_CODES[this.data.ageIndex] : null
    // 头像仅本地缓存展示（隐私指引声明：不存储于服务器）；昵称提交服务器供后台识别发音人
    speaker
      .saveLocalAvatar(this.data.avatarUrl)
      .then(() => {
        const patch = {}
        if (this.data.nickname && this.data.nickname !== '微信用户') patch.nickname = this.data.nickname
        // setProfile 处理画像（性别/年龄段），updateProfile 处理昵称
        return speaker
          .setProfile(g, a)
          .then(() => (Object.keys(patch).length ? speaker.updateProfile(patch) : Promise.resolve()))
      })
      .then(() => {
        wx.hideLoading()
        this.setData({ saving: false })
        wx.showToast({ title: '已保存', icon: 'success' })
        setTimeout(() => wx.navigateBack(), 600)
      })
      .catch((err) => {
        wx.hideLoading()
        this.setData({ saving: false })
        wx.showToast({
          title: '保存失败：' + ((err && err.message) || ''),
          icon: 'none'
        })
      })
  }
})

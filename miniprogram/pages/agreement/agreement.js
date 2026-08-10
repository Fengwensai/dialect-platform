// 协议详情页：按 type 展示三类协议最新版本全文（滚动文本，不用 web-view/rich-text）
const speaker = require('../../utils/speaker')

Page({
  data: {
    title: '',
    version: '',
    content: '',
    loading: true
  },

  onLoad(options) {
    const type = options.type || ''
    speaker
      .getAgreements()
      .then((list) => {
        const item = (list || []).find((a) => a.type === type)
        if (item) {
          wx.setNavigationBarTitle({ title: item.title })
          this.setData({
            title: item.title,
            version: 'v' + item.version,
            content: item.content,
            loading: false
          })
        } else {
          this.setData({ loading: false })
          wx.showToast({ title: '协议不存在', icon: 'none' })
        }
      })
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({
          title: '加载失败：' + ((err && err.message) || ''),
          icon: 'none'
        })
      })
  }
})

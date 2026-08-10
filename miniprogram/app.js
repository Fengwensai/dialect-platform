// 方言采集录音小程序 - 全局入口
const queue = require('./utils/queue')

App({
  globalData: {
    speaker: null // 登录后的发音人档案（冷启动从本地恢复）
  },

  onLaunch() {
    // 恢复登录会话
    const speaker = require('./utils/speaker')
    this.globalData.speaker = speaker.getSpeaker()

    // 隐私授权：全局唯一注册 onNeedPrivacyAuthorization（必须在 onLaunch，页面勿重复注册）
    require('./utils/privacy').init()

    // 初始化队列：确保录音目录存在（上传一律由用户在队列页/我的页点「一键上传」触发，不自动上传）
    queue.init()
  }
})

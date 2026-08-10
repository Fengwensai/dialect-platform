/**
 * 隐私授权弹窗组件（阶段十·上线准备）。
 *
 * 挂到会用隐私接口的页面（login/record/profile）。组件 attached 时向 utils/privacy.js
 * 注册「展示回调」；微信触发 onNeedPrivacyAuthorization 时，privacy 模块调用该回调 → 弹窗。
 *
 * 同意按钮使用官方 open-type="agreePrivacyAuthorization"，微信在用户点击后自动回调
 * resolve（bindagreeprivacyauthorization 内调用 resolve({buttonId,event:'agree'})）；
 * 拒绝按钮手动调用 resolve({event:'disagree'})。
 */
const privacy = require('../../utils/privacy')

Component({
  data: {
    visible: false,
    contractName: ''
  },

  methods: {
    noop() {},

    show() {
      this.setData({ visible: true })
      // 拉官方《隐私保护指引》名称，未配置时兜底默认文案
      privacy
        .getPrivacySetting()
        .then((s) => {
          if (s && s.privacyContractName) {
            this.setData({ contractName: s.privacyContractName })
          }
        })
        .catch(() => {})
    },

    hide() {
      this.setData({ visible: false })
    },

    onAgree() {
      // 官方按钮自动回调：手动 resolve 使隐私接口继续执行
      const resolve = privacy.getResolve()
      privacy.clearResolve()
      if (resolve) resolve({ buttonId: 'privacy-agree', event: 'agree' })
      this.hide()
    },

    onRefuse() {
      privacy.disagree()
      this.hide()
    },

    onOpenContract() {
      privacy.openContract()
    }
  },

  lifetimes: {
    attached() {
      privacy.setPopupHandler(() => this.show())
    },
    detached() {
      privacy.setPopupHandler(null)
    }
  }
})

/**
 * 转发支持（2026-09 修复「转发」置灰）。
 *
 * 微信规则：页面未实现 onShareAppMessage 时，右上角「…」菜单里的「转发」置灰不可点。
 * 此前整包页面都未实现 → 用户无法把小程序转发给好友/群（方言采集靠转发拉同乡，功能等于没开）。
 *
 * 这里给出统一默认转发：卡片标题 + 落到首页。
 * 落地页用首页是因为已整改为「先浏览后登录」——收到卡片的新用户可先浏览、再注册/绑定团队，
 * 不会撞登录墙；分享内容不含任何隐私/会话信息。
 *
 * 页面如有特殊需要，自行覆盖 onShareAppMessage 返回 { title, path, imageUrl } 即可。
 */

const DEFAULT_TITLE = '方言采集录音 · 一起用家乡话留下乡音'

/** 默认转发内容 */
function defaultShare() {
  return {
    title: DEFAULT_TITLE,
    path: '/pages/index/index'
    // 不指定 imageUrl：微信用当前页截图做分享卡，避免引用不存在的资源
  }
}

/** 静态转发回调（不依赖页面 this，可直接挂到 Page 配置上） */
function onShareAppMessage() {
  return defaultShare()
}

/**
 * 分享到朋友圈默认内容。
 * 注意：朋友圈卡片打开的是「分享时所在页面」，无法像转发那样指定落首页，
 * 因此只应挂到未登录也能正常浏览的页面（否则新用户冷启动会落到需登录页成死胡同）。
 */
function onShareTimeline() {
  return { title: DEFAULT_TITLE }
}

module.exports = {
  defaultShare,
  onShareAppMessage,
  onShareTimeline,
  DEFAULT_TITLE
}

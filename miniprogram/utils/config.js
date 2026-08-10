/**
 * 环境配置。
 *
 * API_BASE：后端地址。
 *  - 真机联调（当前默认）：http://10.213.227.166:8000（电脑局域网 IP，手机与电脑同一 Wi-Fi；ipconfig 查当前值）
 *  - 纯开发者工具联调：可临时用 http://127.0.0.1:8000（回环不变，不受 DHCP 影响）
 *  - 正式上线：换成已备案的 HTTPS 域名，并在小程序后台配置 request/uploadFile 合法域名
 * 注意：局域网 IP 由路由器 DHCP 分配，换网络/重启后可能变化，真机联调前需用 ipconfig 复查并更新。
 */
const API_BASE = 'http://10.213.227.166:8000'

module.exports = { API_BASE }

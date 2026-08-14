/**
 * 环境配置。
 *
 * API_BASE：后端地址。
 *  - 正式上线（当前）：https://api.qlzby.com（已备案 + HTTPS，并在小程序后台配置合法域名）
 *  - 本地联调：临时改成局域网 IP（如 http://192.168.x.x:8000，手机与电脑同一 Wi-Fi；
 *    ipconfig 查当前值），或纯开发者工具联调用 http://127.0.0.1:8000；联调完记得改回上线域名。
 */
const API_BASE = 'https://api.qlzby.com'

module.exports = { API_BASE }

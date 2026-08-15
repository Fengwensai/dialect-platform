#!/usr/bin/env node
/**
 * 方言采集平台 · 小程序一键上传
 *
 * 基于微信官方 miniprogram-ci：本地命令行直接上传代码，不用打开微信开发者工具。
 * 注：miniprogram-ci 只有 upload/preview，没有「提交审核」接口（微信保留人工环节），
 *     提审与发布仍要在 mp.weixin.qq.com 手动操作（脚本会提示）。
 *
 * 用法（在 tools/miniprogram 目录下）：
 *   node sync.js check                    # 只校验密钥与配置，不联网
 *   node sync.js upload <版本号> [备注]     # 上传开发版（可到 mp 后台设为体验版秒生效）
 *
 * 例：
 *   node sync.js upload 1.0.1 "修复录音上传超时"
 *
 * 上传后：mp.weixin.qq.com → 版本管理 → 该版本「设为体验版」（内部测）或「提交审核」（对外发布，人工 1~7 天）
 *        审核通过后仍需手动点「发布」。
 *
 * 注意：
 *   - 上传密钥在 keys/upload.key（.gitignore 已封死，绝不提交）
 *   - 首次使用需在微信公众平台「开发设置 → IP白名单」加入本机公网 IP，否则上传报错
 *   - robot=1 固定为机器人1，多机同时传请改 robot 参数
 *   - 每次上传自动在版本备注里署开发者名（DEVELOPER，当前=冯文赛），微信后台版本管理可见
 */
const fs = require('fs')
const path = require('path')
const dns = require('dns')
// 微信 IP 白名单通常只认 IPv4；强制走 IPv4，避免命中 IPv6 被拒
dns.setDefaultResultOrder('ipv4first')
const ci = require('miniprogram-ci')

const REPO_ROOT = path.resolve(__dirname, '..', '..')
const MP_DIR = path.join(REPO_ROOT, 'miniprogram')
const KEY_PATH = path.join(__dirname, 'keys', 'upload.key')
const APPID = 'wx8aa4a30607982887'
const ROBOT = 1
// 版本备注里的开发者署名：每次上传自动追加「开发者 冯文赛」（用户指定，勿改）
const DEVELOPER = '冯文赛'

const cmd = process.argv[2]
const version = process.argv[3]
const desc = process.argv[4] || ''

function fail(msg) {
  console.error(`[x] ${msg}`)
  process.exit(1)
}

function nextSteps() {
  console.log('')
  console.log('下一步（mp.weixin.qq.com → 版本管理，找到刚传的版本）：')
  console.log('  内部测试 → 点「设为体验版」，分享给体验成员，秒生效免审核')
  console.log('  对外发布 → 点「提交审核」（人工 1~7 天）→ 通过后点「发布」才真正上线')
}

// —— 校验密钥与配置（不联网）——
function check() {
  if (!fs.existsSync(KEY_PATH)) {
    fail(`缺少上传密钥 ${KEY_PATH}\n请到 mp.weixin.qq.com → 开发 → 开发设置 → 小程序代码上传 → 生成并下载 .key 后放到 keys/upload.key`)
  }
  const proj = JSON.parse(fs.readFileSync(path.join(MP_DIR, 'project.config.json'), 'utf8'))
  if (proj.appid !== APPID) {
    fail(`project.config.json 的 appid=${proj.appid} 与脚本 APPID=${APPID} 不一致`)
  }
  if (fs.readFileSync(KEY_PATH, 'utf8').startsWith('-----BEGIN RSA PRIVATE KEY-----')) {
    console.log('[✓] 密钥存在且为 RSA 格式')
  } else {
    fail('密钥格式异常（应为 RSA PRIVATE KEY）')
  }
  console.log(`[✓] project.config.json: appid=${proj.appid}, compileType=${proj.compileType}`)
  console.log('[✓] 配置校验通过（上传还需 IP 白名单，见微信后台「开发设置」）')
}

async function makeProject() {
  if (!fs.existsSync(KEY_PATH)) {
    fail(`缺少上传密钥 ${KEY_PATH}`)
  }
  const setting = JSON.parse(fs.readFileSync(path.join(MP_DIR, 'project.config.json'), 'utf8')).setting || {}
  return new ci.Project({
    appid: APPID,
    type: 'miniProgram',
    projectPath: MP_DIR,
    privateKeyPath: KEY_PATH,
    ignores: ['node_modules/**/*'],
    setting,
  })
}

async function upload() {
  if (!version) fail('用法: node sync.js upload <版本号> [备注]')
  // 版本备注自动带开发者署名（用户要求：开发者写 冯文赛）
  const finalDesc = (desc ? `${desc} · ` : '') + `开发者 ${DEVELOPER}`
  console.log(`[i] 上传 ${APPID} 版本 ${version} …（备注: ${finalDesc}）`)
  const project = await makeProject()
  await ci.upload({
    project,
    version,
    desc: finalDesc,
    robot: ROBOT,
    setting: project.setting,
  })
  console.log('[✓] 上传成功！')
  nextSteps()
}

async function main() {
  try {
    if (cmd === 'check') check()
    else if (cmd === 'upload') await upload()
    else fail('用法: node sync.js <check|upload> <版本号> [备注]')
  } catch (e) {
    const msg = (e && (e.message || e)) || '未知错误'
    console.error(`[x] 失败: ${msg}`)
    if (/ip|白名单/i.test(msg)) {
      console.error('  提示：IP 白名单没配或 IP 变了 → 微信公众平台 → 开发 → 开发设置 → IP白名单\n        把本机当前公网 IPv4 加进去（本机 IP 变了需重新加；`curl -4 ifconfig.me` 可查）')
    }
    process.exit(1)
  }
}

main()

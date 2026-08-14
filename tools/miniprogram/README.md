# 小程序一键上传（miniprogram-ci）

基于微信官方 [miniprogram-ci](https://www.npmjs.com/package/miniprogram-ci)，命令行直接上传小程序代码，不用打开微信开发者工具。

> 局限：miniprogram-ci 只有 `upload`/`preview`，**没有「提交审核」接口**（微信保留人工环节）。提审与发布仍需在 mp.weixin.qq.com 手动点。

## 一次性准备（已完成）

- `npm install`（装 miniprogram-ci）
- `keys/upload.key`：微信后台 → 开发 → 开发设置 → 小程序代码上传 → 生成并下载的私钥。
  **此文件已被 `.gitignore` 封死，绝不提交**；换机器或重新授权时重新放入。
- 微信后台「开发设置 → IP白名单」加入本机公网 IP（首次上传不配会报错）。

## 用法（在 `tools/miniprogram` 目录下）

```bash
node sync.js check                        # 离线校验密钥与配置
node sync.js upload <版本号> [备注]        # 上传开发版
```

示例：

```bash
node sync.js upload 1.0.1 "修复录音上传超时"
```

## 上传后

mp.weixin.qq.com → 版本管理 → 找到刚传的版本：

- 内部测试 → 「设为体验版」，分享给体验成员，秒生效免审核
- 对外发布 → 「提交审核」（人工 1~7 天）→ 通过后点「发布」才真正上线

## 说明

- 版本号每次要**递增**（微信不允许覆盖旧版本号），备注写清本次改动，方便审核与回看。
- 提审前先确保**后端已同步线上**（见 `docs/update-workflow.md`），否则审核员打的是旧接口。

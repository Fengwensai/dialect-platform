# 方言采集平台 · 上线部署指南

面向无服务器经验的操作者。按顺序执行即可；带 ☑ 的是**必须做**，其余按需。

## 0. 总体流程

```
建云资源（服务器/域名备案/COS桶） → 改配置 → 部署后端 → 自测 → 上传小程序 → 审核 → 手动发布
```

代码层上线准备（隐私/内容安全/上传限流/微信回调/COS 存储）**已全部完成并本地验证**，
你只需要照着这份指南在真机上落地。运行环境约束见 [platform-dev-constraints] 记忆。

---

## 1. 前置条件（☑ 全部需要）

| 资源 | 说明 |
|---|---|
| 云服务器 | Linux（Ubuntu 22.04 / Debian 12 均可），建议 2 核 4G 起，建议**挂一块数据盘**。省钱可先不买：录音暂落系统盘 `/data`，后续迁 COS 或加盘即可（系统盘 40G 够撑到录音量起来） |
| 域名 | 需**备案**（国内服务器强制，备案本身 1–3 周，建议先办） |
| HTTPS 证书 | 免费 Let's Encrypt / 腾讯云免费证书均可，微信合法域名强制 https |
| 腾讯云 COS 桶（**可选**） | **私有读写**，用于录音存储。**暂不用则跳过，录音自动落服务器本地磁盘**（`MEDIA_ROOT`）兜底，后续可无缝迁移 COS |
| 微信小程序 | 已有 AppID/AppSecret；《用户隐私保护指引》已过审 |

> **两种运行形态，代码都已支持**：
> - **本地磁盘（未配 COS）**：COS 四项留空 → 录音 + 头像全部落 `MEDIA_ROOT`（如 `/data/dialect/media/`），Nginx `/media/` alias 对外。适合刚上线、量还不大的阶段。
> - **COS**：四项填全 → 录音走腾讯云私有桶（预签名 URL），头像仍留本地。量大了随时迁过去（`migrate_recordings_to_cos.py`，无代码改动）。
> 两种形态之间可以随时切换，唯一要注意：`MEDIA_PUBLIC_BASE` 影响微信**音频内容检测**（见 §3.1）。

---

## 2. 建云资源

### 2.1 云服务器
- 装系统时挂载**数据盘**到 `/data`（例：腾讯云挂载后 `sudo mkfs.ext4 /dev/vdb && sudo mount /dev/vdb /data`，并写进 `/etc/fstab` 开机自动挂载）。
- 安全组放行：**22**（SSH）、**80**（HTTP）、**443**（HTTPS）。后端 8000 端口**不要对外开放**，只走 Nginx 反代。

### 2.2 域名
- 备案通过后，把域名解析（A 记录）指向服务器公网 IP。常用两个子域名：
  - `api.你的域名.com` → 后端 + 媒体
  - `admin.你的域名.com` → 管理后台前端（也可不用子域名，直接同域名）

### 2.3 COS 桶（可选，暂不用跳过本节）
> 未配 COS 时录音直接落服务器本地磁盘，本节可完全跳过；后面想上 COS 再回来补即可。
1. 腾讯云控制台 → 对象存储 → 创建存储桶：
   - 地域选**和服务器同地域**（同地域内网互传免流量费）
   - 访问权限选**私有读写**
2. 创建子账号/API 密钥：控制台 → 访问管理 → 访问密钥，新建一对 `SecretId / SecretKey`（只用于此项目）。
3. 记下：**桶名（形如 `xxx-1250000000`，含 `-appid` 后缀）**、**地域（`ap-beijing` / `ap-guangzhou` 等）**、`SecretId`、`SecretKey`。

> ⚠️ **不要**在桶配置里开启 Referer 防盗链，会误伤微信内容安全下载（预签名已限权）。

### 2.4 微信后台配置（☑）
mp.weixin.qq.com → 开发 → 开发设置：
- **服务器域名**：request/uploadFile/downloadFile 合法域名各填 `https://api.你的域名.com`
- **消息推送**：URL 填 `https://api.你的域名.com/api/wechat/callback`，Token 填一个你自己定的串（明文模式），保存时微信会 GET 验签，回显通过即成功。

---

## 3. 改配置（代码已就绪，只改文件不改代码）

### 3.1 `backend/.env`（☑ 完整键名见 `backend/.env.example`）
```ini
DATABASE_URL=postgresql+psycopg://dialect:你的密码@localhost:5432/dialect_admin
JWT_SECRET=<openssl rand -hex 32 生成的串>
JWT_EXPIRE_MINUTES=720
ADMIN_INIT_PASSWORD=<设一个强密码，init_db.py 建种子管理员用>
WECHAT_APPID=<你的 AppID>
WECHAT_SECRET=<你的 AppSecret>
MEDIA_PUBLIC_BASE=            # 见下方说明①
CORS_ORIGINS=https://admin.你的域名.com
MAX_RECORDING_SIZE_MB=10
WECHAT_MSG_TOKEN=<与微信后台消息推送一致的 Token>
# —— 存储：四项全留空 = 本地磁盘兜底（刚上线推荐）；想上 COS 再填 §2.3 的四个值 ——
COS_SECRET_ID=
COS_SECRET_KEY=
COS_REGION=
COS_BUCKET=
MEDIA_ROOT=/data/dialect/media
# —— 限流（默认值已够用，可不填）——
# 登录：连续 LOGIN_FAIL_LIMIT 次失败后锁定 LOGIN_FAIL_WINDOW_SECONDS 秒（账号/IP 各一份，成功即清零）
LOGIN_FAIL_LIMIT=5
LOGIN_FAIL_WINDOW_SECONDS=900
LOGIN_IP_FAIL_LIMIT=20
# 上传：单个发音人 UPLOAD_RATE_LIMIT 次 / UPLOAD_RATE_WINDOW_SECONDS 秒
UPLOAD_RATE_LIMIT=60
UPLOAD_RATE_WINDOW_SECONDS=600
```
> ① **`MEDIA_PUBLIC_BASE` 只影响微信「音频内容检测」**：留空 → 异步音频检测自动跳过（fail-open，文字检测不受影响，业务不阻断）；填 `https://api.你的域名.com` → 微信内容安全服务器可下载 `/media/` 下的录音做检测（此时 Nginx `/media/` 需公网可访问，见 §4.5）。
> ⚠️ 若填了 COS 四项并启用 COS：**先别重启服务**，按 §4.3 顺序回填再重启。`.env` 含真实凭据，切勿提交/外发。

### 3.2 `miniprogram/utils/config.js`（☑）
```js
const API_BASE = 'https://api.你的域名.com'
```

---

## 4. 部署后端

### 4.1 上传代码 + 装依赖
```bash
# 把 backend/ 目录传到服务器，如 /opt/dialect/backend
cd /opt/dialect/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 再按 §3.1 编辑 .env
```

### 4.2 数据库（☑）
```bash
# 1. 安装 PostgreSQL（Ubuntu: sudo apt install postgresql）
sudo -u postgres psql < scripts/create_db.sql        # 建库建用户（按需改密码）
# 2. 建表 + 行政区划 + 种子管理员（幂等，可重复跑）
#    ⚠️ 建种子管理员前，先在 .env 设 ADMIN_INIT_PASSWORD=<强密码>（后台无改密接口；
#        不设则默认 admin/admin123，等于公开后台）。本地联调可保持默认。
.venv/bin/python scripts/init_db.py
# 3. 各阶段迁移脚本（幂等，全部跑一遍）
for s in migrate_word_status migrate_speaker_region migrate_task_team_code \
         migrate_agreements migrate_recording_content_check migrate_recordings_transcripts \
         migrate_demo_tasks migrate_task_claims; do
  .venv/bin/python scripts/$s.py
done
# 4. 建种子团队码 HB-SJZ（回归脚本依赖，见 §5.1）
#    用第 2 步建的 admin 登录拿 token 后：
curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_INIT_PASSWORD 同值>"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])" > /tmp/tok
curl -s -X POST http://127.0.0.1:8000/api/team-codes \
  -H "Authorization: Bearer $(cat /tmp/tok)" \
  -H 'Content-Type: application/json' \
  -d '{"code":"HB-SJZ","name":"石家庄团队","province_code":"13","city_code":"1301"}'
```

### 4.3 COS 回填（仅启用 COS 时需要；本地磁盘模式跳过本节）
```bash
# 未配 COS（四项留空）→ 跳过：录音已直接落本地磁盘，无需回填。
# 已填 COS 四项但服务未重启时：
.venv/bin/python scripts/migrate_recordings_to_cos.py   # 把存量本地录音上传 COS
```
输出 `migrated=N missing=0` 后，才重启服务进入 COS 模式。

### 4.4 常驻服务（systemd，☑）
新建 `/etc/systemd/system/dialect-api.service`：
```ini
[Unit]
Description=dialect-platform api
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/dialect/backend
ExecStart=/opt/dialect/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dialect-api
```
> 只监听 127.0.0.1，由 Nginx 反代对外。多 worker 用 `--workers 2` 也行，无冲突。

### 4.5 Nginx + HTTPS（☑）
```nginx
server {
    listen 80;
    server_name api.你的域名.com;
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 443 ssl;
    server_name api.你的域名.com;
    ssl_certificate     /etc/ssl/cert.pem;      # Let's Encrypt / 腾讯云证书
    ssl_certificate_key /etc/ssl/key.pem;

    client_max_body_size 12m;                    # 录音上限 10MB + 余量
    location /media/ {                           # 本地媒体：头像 +（未配 COS 时）全部录音
        alias /data/dialect/media/;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
管理后台前端（Vue3）：构建后 `npm run build` 产出 `dist/`，由 Nginx 静态托管到 `admin.你的域名.com`。
**关键**：后台的 axios 用相对路径 `/api`、`<audio>` 试听走 `/media/`，所以 admin 域名也必须把这两条反代到后端，否则后台登录/试听全断：
```nginx
server {
    listen 80;
    server_name admin.你的域名.com;
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 443 ssl;
    server_name admin.你的域名.com;
    ssl_certificate     /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;

    client_max_body_size 12m;
    root /opt/dialect/frontend/dist;             # npm run build 产物
    index index.html;

    location /api/  { proxy_pass http://127.0.0.1:8000; }   # 后台接口
    location /media/ { alias /data/dialect/media/; }        # 头像 + 录音试听
    location / {
        try_files $uri $uri/ /index.html;                    # SPA 回退
    }
}
```
（若管理后台与 API 共用同一域名，只需把 `/api/`、`/media/`、静态托管并进同一个 server 块。）

---

## 5. 部署后自测（☑ 上线前必须）

### 5.0 就绪探活（统一用健康检查端点）

```bash
curl -i http://127.0.0.1:8000/api/health     # 期望 200 + {"status":"ok","db":true}
curl -i https://api.qlzby.com/api/health     # 公网反代下同样 200（DB 挂时返回 503+db:false）
```
该端点每次探测 DB 连通性（`SELECT 1`），DB 不可达 5s 内返回 503 —— 也是服务器自愈监控与 UptimeRobot 的判断依据，详见 `docs/health-monitoring.md`。

### 5.1 后端回归（服务器上跑）
按固定顺序（test_api 会清业务表，放最前）：
```bash
cd /opt/dialect/backend
for s in test_api verify_agreements verify_region_isolation verify_task_team_code \
         verify_mp_full_flow verify_wechat_callback verify_cos_mode \
         verify_demo_task verify_rate_limit verify_task_claims \
         verify_quality_check; do
  .venv/bin/python scripts/$s.py || echo "FAIL: $s"
done
```
全部 PASS。注意：
- `verify_region_isolation` / `verify_task_team_code` **依赖种子团队码 `HB-SJZ`**（13/1301）。部署时已在 §4.2 第 4 步建好；若跑过 `reset_business_data.py` 清库（会 TRUNCATE 团队码），需重新执行那一步。
- 未配 COS 时 `verify_cos_mode.py` 用内置 fake COS 客户端校验上传/预签名逻辑，照常可跑；`verify_mp_full_flow` 会真实上传并自动清理。

### 5.2 手动闭环
按 `docs/launch-check.md` §3–7：后台建团队/词条/任务 → 小程序登录/同意协议/绑团队/**领取词条**/录音上传 → 后台审核试听 → 导出 ZIP → 内容安全。
重点验证：
- **本地磁盘模式**：浏览器打开审核页试听一段录音（`<audio>` 请求 `https://api.你的域名.com/media/...` 能播）；上传一条新录音后确认 `/data/dialect/media/recordings/` 下有新文件。
- **COS 模式**：试听走 COS 预签名 URL；上传新录音确认进了 COS 桶。

---

## 6. 发布小程序（☑）

### 6.0 审核前：建演示任务（☑ 建议）

微信审核员是**全新用户、没有团队码**。录音页/任务页对未绑定团队用户本来为空（服务端按属地过滤），
审核员会录不了音 → 易被判「核心功能无法体验」。已内置**演示任务**机制解决：

1. 后台「任务分配」→ 勾选 **演示任务** → 选 2~3 条词条 → **创建并发布**（演示任务无视投放区划，全国未绑定用户可见）。
2. 提交审核时在「备注」里写：*打开小程序 → 登录并同意协议 → 直接进入「任务」选「演示任务」录音 → 保存 → 我的页查看时长统计*。
3. 审核通过后清理演示数据：
   ```bash
   .venv/bin/python scripts/cleanup_demo_recordings.py          # 删除演示录音、关闭演示任务（可复用）
   .venv/bin/python scripts/cleanup_demo_recordings.py --hard   # 连同演示任务一并删除
   ```
   （演示任务仅未绑定团队用户可见可录；已绑定用户即使知道任务 ID 也会 403，演示数据与正式数据隔离。）

1. 微信开发者工具打开 `miniprogram/`，填好 AppID（已在 `project.config.json`）。
2. 详情 → 本地设置 → 勾选「不校验合法域名」（仅开发联调用）。
3. 真机预览/体验版回归一遍 `docs/launch-check.md` 的清单（隐私弹窗、录音权限、上传、昵称）。
4. 工具栏「上传」→ 填版本号备注 → 提交。
5. mp.weixin.qq.com → 版本管理 → 提交审核（微信人工审核，1–7 天）。
6. **审核通过后手动点「发布」** 才真正上线（不是自动）。

---

## 7. 存储规划（供长期参考）

| 内容 | 存储位置 | 说明 |
|---|---|---|
| 录音 | 未配 COS：本地 `/data/dialect/media/recordings/`；配 COS 后：腾讯云私有桶 | 本地模式量大了注意**数据盘容量 + 备份** |
| 头像 | 服务器本地 `/data/dialect/media/avatars/` | 体量小，/media 挂载服务 |
| 数据库 | 服务器本地 PostgreSQL | 建议数据目录也放数据盘 |

- **备份（本地磁盘模式更要勤）**：**已落地** —— `backend/scripts/backup.sh` 每日 cron（03:17）执行，`pg_dump` 全库 + `/data/dialect/media/` 打包 + `.env` 快照到 `/data/dialect/backups`，保留 14 天；还原步骤见 `docs/backup.md`。`/data/dialect/media/` 可另随数据盘快照/整机快照一起备份；配了 COS 则桶开版本控制或定期快照，并建议把备份产物同步到云端异地副本。
- 未来录音量/流量再大时，COS 可加 CDN 加速（把桶访问权限切 CDN 域名），无需改代码（预签名 URL 域名换 CDN 即可）。

---

## 8. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 上传报「录音文件过大」 | `.env` 的 `MAX_RECORDING_SIZE_MB` 与 Nginx `client_max_body_size` 都够不够 |
| 后台登录提示「尝试过于频繁」 | 连续输错被防爆破锁定（`LOGIN_FAIL_LIMIT` 次/窗口，默认 5 次/15 分钟）；等窗口过或用 `scripts/` 直接改库/重启可恢复，正常登录成功后自动清零 |
| 小程序上传报「上传过于频繁」 | 单发音人超 `UPLOAD_RATE_LIMIT` 条/窗口（默认 60 条/10 分钟）；本地队列稍后自动重传，无需人工处理 |
| 审核页/试听 403 或 5 分钟后失效 | COS 模式：预签名 `Expired` 默认 3600s，查服务器时间（`timedatectl`，需 NTP 校时）；本地模式：确认 Nginx `/media/` alias 指向 `MEDIA_ROOT` |
| 微信内容安全一直不回调 | ① 消息接收 URL 未配/Token 不一致；② 本地模式 `MEDIA_PUBLIC_BASE` 留空（音频检测本就跳过，文本检测照常）；③ COS 模式录音未回填；④ 桶开了防盗链 |
| 上传新录音后桶里没有 | COS 模式：服务未重启（`.env` 是启动时加载）或四项没填全。本地模式：看 `/data/dialect/media/recordings/` 有没有文件 |
| 本地磁盘越来越大 | 录音全在服务器盘上，注意 `MEDIA_ROOT` 所在盘容量；可后续迁移 COS 释放 |
| `migrate_recordings_to_cos` 提示 COS 未启用 | 先确认 `.env` 四项填全再跑 |
| 改 `.env` 不生效 | **必须重启服务**：`sudo systemctl restart dialect-api` |

---

## 9. 还需要你人工做的事（不属于代码）

- [ ] 域名备案 + HTTPS 证书
- [ ] 微信后台：服务器域名、消息推送 URL、Token 与 `.env` 一致
- [ ] 建私有 COS 桶 + API 密钥（**可选**，暂不用则跳过，录音先落本地磁盘）
- [ ] 上线后观察：上传是否正常、内容安全是否回调（本地模式若 `MEDIA_PUBLIC_BASE` 留空则音频检测跳过）、试听是否流畅、数据盘容量

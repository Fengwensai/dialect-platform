# 方言采集平台 · 日常更新流程（本地改 → 线上同步）

> 适用：**首次部署已完成**后，日常改业务逻辑（后端 / 管理后台 / 小程序）并把改动同步到线上。
> 首次部署见 `docs/deploy-guide.md`；线上现状见 README「生产部署」与记忆。
> 改本地后端的环境约束（uvicorn 无热载、GBK、真实凭据等）见记忆 `platform-dev-constraints`。

## 0. 核心认知：一次改动可能涉及三处线上产物

| 改了什么 | 需要同步到哪里 | 生效方式 |
|---|---|---|
| 后端（backend/） | 服务器 `/opt/dialect/backend` | `git pull` + **重启 systemd 服务** |
| 管理后台（frontend/） | 服务器 `/opt/dialect/frontend/dist` | 重新 `npm run build` + 上传 dist |
| 小程序（miniprogram/） | 微信平台 | 开发者工具「上传」→ 提审（1~7 天）→ 发布 |

**最容易漏的两处**：① 后端改了不重启不生效（`.env` 是启动时加载）；② 管理后台本地 `5173` dev 跑通 ≠ 线上生效，必须重新 build + 传 dist。

---

## 1. 本地开发与验证（每次动手先走这套）

```bash
# 后端：改完按「kill + 重启」加载
#   查占用 8000 的进程 PID 并 kill，然后后台重启（无 --reload，不会自动加载）
netstat -ano | grep :8000          # 找到 PID
taskkill //PID <PID> //F
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn-current.log 2>&1 &
```

回归脚本（**固定顺序**，test_api 会清业务表放最前；依赖种子团队码 `HB-SJZ`）：

```bash
cd backend
for s in test_api verify_agreements verify_cos_mode verify_dashboard verify_demo_task \
         verify_mp_full_flow verify_rate_limit verify_region_isolation verify_review_batch \
         verify_review_reset_delete verify_speaker_merge verify_task_claims \
         verify_task_team_code verify_wechat_callback verify_word_merge \
         verify_audit_log verify_quality_check; do
  ./.venv/Scripts/python.exe scripts/$s.py || echo "FAIL: $s"
done
```

```bash
# 管理后台：确保能编译
cd frontend && npm run build
# 小程序：开发者工具编译 + 真机预览（录音必须在真机验证）
```

## 2. 提交并推送（服务器从 GitHub 拉，所以先保证 GitHub 最新）

```bash
git status                       # 确认改动符合预期
git add -A
git commit -m "feat/fix: 本次改动说明"
git push origin master
```

> 推 master 后 **GitHub Actions 自动跑 CI**（`ci.yml`）：后端 16 脚本全量回归（一次性 postgres 库，不碰真实数据）+ 前端 `npm run build`。到仓库 **Actions** 页看是否全绿，红了先修再部署。

**提交前必查**（`.gitignore` 已封死，别手滑放行）：

```bash
git status --short | grep -iE '\.env$|deploy-bundle|\.log$|media/|\.tar\.gz$|secrets' || echo "干净"
```

> 返回「干净」才能 push。`.env`、`deploy-bundle-*.tar.gz`、`backend/media/`、日志**永远不进仓库**。

## 3. 同步后端到服务器（☑ 后端有改动必做）

### 方式 C：GitHub Actions Deploy 按钮（**推荐**，替代手动 scp + systemctl）

推完 master 后，仓库 **Actions → Deploy → Run workflow** 一键部署：
在 runner 上构建前端 dist → rsync 后端（排除 `.env`/`.venv`/`media`）+ 前端 dist 到服务器 → `pip install` → 跑 `init_db.py` + 输入框指定的迁移脚本 → `systemctl restart dialect-api` → 探活 `/api/health` 就绪。

**首次使用前配 3 个 GitHub Secrets**（仓库 Settings → Secrets and variables → Actions → New repository secret）：

| Secret | 值 |
|---|---|
| `DEPLOY_SSH_KEY` | 本机 `~/.ssh/id_ed25519` 的**内容**（能免密登录服务器 root 的那把） |
| `DEPLOY_HOST` | `182.92.9.204` |
| `DEPLOY_USER` | `root` |

**Run workflow 时**：若本次新增了迁移脚本，在 `migrations` 输入框填空格分隔的名字（如 `migrate_task_claims migrate_word_status`，可带可不带 `.py`）；没有就不填。

> 回退到手动 rsync（Actions 抽风/服务器想就地操作用）：见下方方式 B。

### 方式 A：服务器作为 git 仓库（备用，改动只传 diff）

**一次性配置**（目前服务器是打包部署，还没有 .git；先做这一次）：

```bash
ssh root@<服务器IP>
cd /opt/dialect
git clone git@github.com:Fengwensai/dialect-platform.git backend-new
# 保留现网配置与数据：把现有 .env 拷过去，media 目录不动
cp backend/.env backend-new/.env
cp backend/scripts/create_db.sql backend-new/scripts/ 2>/dev/null   # 如需
# 停旧服务，切目录，起新服务（注意 systemd 里的 WorkingDirectory 一起改）
sudo systemctl stop dialect-api
mv backend backend-old.$(date +%Y%m%d)
mv backend-new backend
sudo systemctl start dialect-api
# 确认无误后删旧：rm -rf backend-old.*
```

**日常更新**：

```bash
ssh root@<服务器IP>
cd /opt/dialect/backend
git pull                                  # .env 在 gitignore，不会被覆盖，安全
# 依赖有变更时：
.venv/bin/pip install -r requirements.txt
# 本次新增了迁移脚本时（幂等，可重复跑）：
for s in <本次新增的迁移脚本名>; do .venv/bin/python scripts/$s.py; done
# 重启加载新代码 + .env：
sudo systemctl restart dialect-api
# 看日志确认无报错：
sudo journalctl -u dialect-api -n 50
```

### 方式 B：rsync 增量（服务器暂不接 git 时用）

```bash
# 本地（Git Bash）：把 backend/ 同步过去，排除 .venv/.env/media
rsync -avz --exclude '.venv' --exclude '.env' --exclude 'media' \
  backend/ root@<服务器IP>:/opt/dialect/backend/
# 然后照样：pip install（如依赖变）→ 跑迁移 → restart
```

> rsync 会把新文件也带过去，但**不会删除服务器上多余文件**（含 .env），比整包解压安全。

## 4. 管理后台有改动 → 重新 build + 上传 dist

```bash
cd frontend && npm run build              # 产出 dist/
# 上传（--delete 会清掉服务器旧 dist，避免残留旧 chunk）
rsync -avz --delete frontend/dist/ root@<服务器IP>:/opt/dialect/frontend/dist/
```

静态文件即传即生效，Nginx 不用动、不用重启。

## 5. 小程序有改动 → 一键上传 + 手动提审

前提（一次性，已配好）：`tools/miniprogram/keys/upload.key` 存在（微信后台下载的上传密钥，`.gitignore` 已封死）；依赖已装（`cd tools/miniprogram && npm install`）；微信后台「开发设置 → IP白名单」已加入本机公网 IP（首次上传会提示）。

```bash
cd tools/miniprogram
node sync.js check                              # 离线校验密钥与配置
node sync.js upload 1.0.1 "本次改动说明"          # 一键上传开发版（不开开发者工具）
```

上传成功后（miniprogram-ci 无「提审」接口，微信保留人工环节）：
- 内部测试 → mp.weixin.qq.com → 版本管理 → 该版本「设为体验版」，分享给体验成员，**秒生效免审核**
- 对外发布 → 该版本「提交审核」（人工 1~7 天）→ 通过后**手动点「发布」**

> 回退到开发者工具手动上传（miniprogram-ci 报编译错时）：工具栏「上传」→ 版本号 + 备注 → mp 后台「提交审核」→ 通过后「发布」。

**迭代期技巧**：
- 内部测试用**体验版**（免审核），只在要正式发布时才提审。
- 小程序和后端改动**一起发**：小程序提审前先确认后端已同步（第 3 步），否则审核员打开线上小程序打的是旧接口。
- 若改的是 `miniprogram/utils/config.js` 的 `API_BASE`：生产值应是 `https://api.qlzby.com`，别在联调时把它带回仓库。

## 6. 一键检查清单（每次发布前过一遍）

- [ ] GitHub Actions **CI** 全绿了吗（16 脚本回归 + 前端 build，红了先修再部署）
- [ ] 后端改动 → 用 **Actions Deploy 按钮**（或手动 `git pull`/rsync）+ 迁移脚本 + `systemctl restart dialect-api` 了吗
- [ ] 管理后台改动 → Deploy 按钮已同步 dist（或手动 `npm run build` + 上传 dist；5173 跑通 ≠ 线上生效）
- [ ] 小程序改动 → 开发者工具上传 + 提审了吗
- [ ] 数据库结构变更 → 迁移脚本写了吗、`docs/schema.sql` 更新了吗
- [ ] 新增依赖 → 服务器 `pip install -r requirements.txt` 了吗
- [ ] `git status` 复查无 `.env` / `deploy-bundle-*` / `media/` 等敏感文件
- [ ] 改协议/领取制/演示任务等业务规则 → 后台页面有对应操作入口吗、文档同步了吗
- [ ] 发布小程序前 → 后端已在线上、演示任务还在（提审期）、审核通过后记得 `cleanup_demo_recordings.py` 清理

## 7. 出错时的快速回退

- **后端坏了**：服务器上 `sudo journalctl -u dialect-api -n 100` 看日志 → 改 `git log --oneline -1` 确认本次提交 → `git reset --hard <上一个好commit>` → `restart`。`.env` 不受影响。
- **前端白屏**：多半是 `npm run build` 失败或 dist 传错 → 重新 build 再传；或回退 dist 备份。
- **小程序出问题**：线上还是旧版（新版本只有提审通过+发布才生效），撤不发布即可；体验版随意。

---

> 首次完整部署（建资源/域名/COS/systemd/Nginx）仍看 `docs/deploy-guide.md`。

# 方言采集平台

- **阶段一**（Week 1-2）：管理后台 —— Excel 词表解析入库 + 任务分配。
- **阶段三~六**（Week 3-4+）：小程序发音人端 —— 核心录音器（PCM→WAV + 本地缓存队列），已打通**「录→传→库」闭环**，并完成**阶段二全部接口**（微信登录 / 领任务 / 词条列表 / 进度）、**阶段三录音审核**（后台试听 → 转写 → 通过/驳回，`approved/rejected` 流转打通）、**阶段四数据集导出**（approved 录音批量导出 ZIP + manifest.csv）、**阶段五发音人画像采集**（性别/年龄段，登录+上传附带、可自助改、manifest 扩列）与**阶段六后台发音人管理**（列表/筛选/编辑画像，省隔离），真机端到端验证。
- **阶段八**（团队绑定属地隔离）：发音人凭**团队码**绑定省+市属地（一码一区），**只能看到/录制本地区任务**（服务端按省+市严格过滤任务/词条/上传，客户端无法绕过）；管理后台新增「团队管理」页（团队码 CRUD）+「发音人管理」属地纠错（改属地自动解除团队绑定）+「任务分配」**关联团队码**（投放区划由团队码自动带出），省管理员仅能管理本省团队码/发音人/团队任务。
- **阶段九**（三份协议登录确认）：用户协议 / 隐私政策 / 声音单独授权协议三份协议，小程序登录时**三勾选全部同意才能登录**（不勾选无法登录）；后台「协议管理」页可编辑（编辑=生成不可变新版本，发布后所有发音人需重新同意），后端对未同意最新版的功能接口**强制 403**，客户端无法绕过。
- **阶段十二**（管理后台数据看板 + 数据质量）：后台新增「**数据看板**」页 —— 平台/本省**概览数字卡片**（发音人/录音/待审/通过/驳回/总时长/有效时长/通过率）+ **近 7/30 天录音趋势数字卡片** + **词条采集难度表**（按词条聚合录音/通过/驳回/通过率/驳回率，默认驳回多优先）+ **区域分布小表** + **每发音人一行关键指标的明细表**（录音/审核/时长/通过率/任务数/词条数/最近活跃，可筛选、5 种排序、导出时长 CSV），点进发音人可下钻**录音明细**（试听/筛选/导出）与**领取记录**（词条/任务/是否已录）。省管理员自动钳制为本省数据。
- **数据质量治理**（后台完善项 4/5）：词条编辑保存前**查重提示**（仅提示不拦截，方言词同词异音可确认后保存）；词条库 / 发音人管理支持**合并**（把重复词条/多身份发音人并为一个，录音/领取/任务引用按状态保留策略迁移去重，淘汰者连带清理存储文件，词条合并且自动处理任务条目冲突）；看板补**录音趋势**与**词条采集难度**两个时间/质量维度。

## 目录

- [管理后台（backend / frontend）](#管理后台backend--frontend)
- [小程序发音人端（miniprogram）](#小程序发音人端miniprogram)

---

# 管理后台（backend / frontend）

## 技术栈

- 后端：Python 3.13 + FastAPI + SQLAlchemy 2 + PostgreSQL 15
- 前端：Vue 3 + Vite + Element Plus + Pinia
- 行政区划：内置静态省市区数据（`backend/data/pca-code.json`，3429 条，31 省）

## 项目结构

```
backend/                     # FastAPI
  app/
    core/                    # 配置、JWT/密码、鉴权依赖
    models/                  # 数据模型
    schemas/                 # Pydantic 校验
    routers/                 # auth/excel/words/regions/tasks/users/agreements/mp/review/team_codes
    services/                # Excel 解析、区划匹配、微信登录
  scripts/
    create_db.sql            # 建库（需 postgres 超级用户密码）
    init_db.py               # 建表 + 灌区划 + 种子管理员
    make_sample_xlsx.py      # 生成样例词表
    test_api.py              # 后端全流程冒烟测试
  data/
    pca-code.json            # 中国行政区划静态数据
    河北省词表.xlsx          # 样例词表
  media/                     # 录音文件静态目录（/media 挂载）
frontend/                    # Vue3 管理端
  src/views/                 # 登录、词表导入、词条管理、任务分配、区划、管理员、录音审核、发音人管理、团队管理、协议管理
miniprogram/                 # 微信小程序（发音人录音端）
  utils/                     # recorder/wav/queue/uploader/config/speaker/fmt/api/region
  pages/                     # login(登录门禁·协议三勾选·团队码)/agreement(协议全文)/index(首页·录音台·绑定弹窗)/mine(我的·个人中心)/record/queue/tasks/words/profile
  tools/test_wav.js          # WAV 头 Node 自检
```

## 快速开始

### 1. 建库（首次）

```bash
# 在 backend 目录下，输入 postgres 超级用户密码
"/d/PostgreSQL/15/bin/psql.exe" -U postgres -h localhost -f scripts/create_db.sql
# 建表 + 灌入行政区划 + 种子管理员
./.venv/Scripts/python.exe scripts/init_db.py
```

### 2. 启动后端

```bash
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

前端已配置 `/api` 代理到后端 `:8000`。

## 默认账号

| 账号 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123` | 超级管理员（全国） |
| `hebei_admin` | `admin123` | 河北省管理员（仅河北） |

## 常用脚本

- 生成样例词表：`python backend/scripts/make_sample_xlsx.py`
- 后端冒烟测试：`python backend/scripts/test_api.py`（需后端已启动）
- 领取制迁移（幂等，建表+回填）：`python backend/scripts/migrate_task_claims.py`
- 领取制专项验证（进程内 22 项断言）：`python backend/scripts/verify_task_claims.py`
- 生成测试 Excel 后，在前端「词表导入」页上传即可走通全流程

## 环境配置

后端配置在 `backend/.env`：

- `DATABASE_URL`：`postgresql+psycopg://dialect:密码@localhost:5432/dialect_admin`
- `JWT_SECRET`：改成一个长随机字符串

> 生产部署注意：`JWT_SECRET` 必须更换；前端 CORS 目前全放开，上线前需收紧。

---

# 小程序发音人端（miniprogram）

原生微信小程序，对应 plan.txt **Week 3-4**：核心录音器调通，重点攻克 **PCM→WAV** 与 **本地缓存队列**，并已在**真机**端到端验证「录 → 传 → 库」闭环；阶段二剩余接口（微信登录 / 领任务 / 词条列表 / 进度）已全部实现。

## 已实现

| 模块 | 文件 | 说明 |
|---|---|---|
| PCM→WAV | `miniprogram/utils/wav.js` | 纯函数补 44 字节**小端** WAV 头（`DataView.setUint*` 第 3 参 `true`），不依赖 wx，可 Node 单测 |
| 录音封装 | `miniprogram/utils/recorder.js` | `RecorderManager` 强制 `format:'PCM'`（大写）/ 16kHz / 16bit / 单声道 / 60s，Promise API |
| 本地缓存队列 | `miniprogram/utils/queue.js` | 元数据 `wx.setStorage` + 音频 `USER_DATA_PATH/records/`；重录覆盖、一键提交（完全手动，无任何自动上传）、失败保留不中断 |
| 真实上传 | `miniprogram/utils/uploader.js` | `USE_MOCK=false`，`wx.uploadFile` → `POST /api/mp/recordings`（multipart：file + task_id/word_id/duration/device_id；已登录自动带 Bearer token） |
| 环境配置 | `miniprogram/utils/config.js` | `API_BASE` 指向后端地址（真机联调填电脑局域网 IP，当前 `http://192.168.1.70:8000`，DHCP 变址需同步改） |
| 发音人身份 | `miniprogram/utils/speaker.js` | 稳定 `device_id` + 微信登录（`wx.login` → `POST /api/mp/login` 换 token，`openid` 与 `device_id` 绑定统一身份，token/speaker 本地持久化） |
| 请求封装 | `miniprogram/utils/api.js` | `wx.request` Promise 化，自动带 `Authorization: Bearer <token>`，401 清 token 提示重登 |
| 登录页 | `pages/login` | **强制微信登录门禁**：`wx.login` 静默换 token → 完善资料（官方 `chooseAvatar` 头像 + `type=nickname` 昵称 + 性别年龄段选择器 + **团队码输入框（未绑定必填，保存时 `POST /api/mp/team/join` 一并绑定属地）**，均可跳过/暂不绑定，保存调 `POST /api/mp/profile`）→ `switchTab` 进首页；已登录冷启动直接跳首页。`wx.getUserProfile` 自 2022 年受限已不再使用 |
| 首页 | `pages/index` | **录音台（精简版）**：欢迎语 + **大号渐变「领取任务」主按钮（最醒目）** + 「开始录音」大按钮 + 提示其余功能在「我的」；**未加入团队时顶部提示条 → 弹窗输入团队码绑定** |
| 我的 | `pages/mine` | **个人中心 + 功能卡片**：顶部用户卡汇总（头像 / 姓名 / **属地（省·市，`utils/region.js` 只读展示，未绑定显示「未加入团队」）** / 性别·年龄段），**点击整卡进入 `pages/profile` 编辑页**；**常用功能卡片（录音队列 / 一键上传含进度 / 审核进度→详情页 / 导出录音时长 / 使用说明，点击触发）** + 退出登录（回登录页）；下拉刷新。**导出录音时长**：`GET /api/mp/me/durations` 预览统计（总数/总时长/有效·无效时长）→ `GET /api/mp/me/export` 下载 CSV（`utf-8-sig`，列同后台发音人明细导出）→ 存本地 → 分享到文件传输助手 |
| 资料编辑页 | `pages/profile` | **头像（`chooseAvatar`，先 `POST /api/mp/avatar` 上传成服务器路径再保存，跨设备持久）/ 姓名（`type=nickname`）/ 属地（团队码绑定，**只读**展示「省·市」）/ 性别 / 年龄段**，保存走 `POST /api/mp/profile`（**不含 `province_code`**——属地唯一来源是团队码绑定） |
| 任务页 | `pages/tasks` | **所属地区只读展示（`省·市` 或「未绑定团队」，无选择器——服务端强制按属地过滤）** + 已发布任务列表（`GET /api/mp/tasks`，含词条数/已录进度，**进度条以「需录 N 条」为目标**，`min(100, 已录/需录×100)`）；下拉刷新 |
| 词条页 | `pages/words` | 任务词条列表（`GET /api/mp/tasks/{id}/words`），按审核状态标 chip（待审核/已通过/需重录），合并本地队列状态，头部显示需重录数，**已通过词条展示审核转写参考（普通话/方言）**，点击进入录音；下拉刷新 |
| 录音页 | `pages/record` | **先选任务→再选词条**（复用 `GET /api/mp/tasks` + `GET /api/mp/tasks/{id}/words`，词条内容/发音提示/例句自动带入、标注审核状态 chip），支持词条页/队列页带参直接录音、可「换词条」；录音中**返回拦截**防误退出 |
| 队列页 | `pages/queue` | 队列（状态+操作）+ **批量删除**（勾选多条→删除所选）+ **一键上传**（完全手动，无自动上传）；下拉刷新 |
| 审核进度页 | `pages/progress` | **审核进度详情**：总体汇总（已通过/待审核/需重录/已录）+ **按任务拆分**（`GET /api/mp/tasks` + 逐任务 `GET /api/mp/recordings/progress?task_id=` 并行拉取），点任务卡片进词条页可重录；下拉刷新 |

### 页面结构与登录门禁

小程序底部 **TabBar = 首页 / 我的**（**图标 + 文字**，图标为 `images/tab/` 下 81×81 PNG，未选中灰 / 选中品牌蓝），各司其职：

- **首页（录音台·精简）**：欢迎语 + 醒目「领取任务」大按钮 +「开始录音」按钮 —— 只保留两大核心入口。
- **我的（个人中心 + 功能卡片）**：顶部用户卡汇总头像 / 姓名 / 方言点 / 性别·年龄段，点击进入**资料编辑页**（`pages/profile`）；以及**常用功能卡片**（录音队列、一键上传、审核进度、使用说明，点击触发），退出登录。
- **强制登录门禁**：`pages/login/login` 为入口页，打开小程序即要求微信登录（`wx.login` 静默换 token，不弹授权窗）；登录成功后进入「完善资料（可选）」步骤（官方头像昵称填写能力 + 性别年龄段选择器，均可跳过，保存调 `POST /api/mp/profile`），完成后 `switchTab` 进入首页。已登录用户冷启动自动跳过登录页。

## 闭环验证结果（真机实测）

「录 → 传 → 库」已**端到端验证通过**：

| 环节 | 验证内容 | 结果 |
|---|---|---|
| 录音 → WAV | 真机 RecorderManager 录 PCM → `wav.js` 补 44 字节小端头 | 落库 WAV 经 Python `wave` 校验：16000Hz / 单声道 / 16bit / 帧数=时长 |
| 本地队列 | 录音保存入队、状态流转 `pending→uploading→done` | ✅ |
| 真实上传 | `wx.uploadFile` → `POST /api/mp/recordings`，随附 `device_id` | 200，返回 `recording_id` / `audio_url` |
| 发音人建档 | 首次上传按 `device_id` 自动 upsert `speakers` 行（`openid` 预留） | ✅ |
| 后端校验 | 任务不存在 → 404；词条不属于任务 → 400；空文件 → 400 | ✅ |
| 重录覆盖 | 同 `(task, word, speaker)` 再传 → `overwritten:true`，保持 recording id、删旧文件 | ✅ |
| 静态试听 | `GET /media/recordings/...` 直接可播放 | 200 |

**联调环境**：后端 `uvicorn --host 0.0.0.0 --port 8000` 监听局域网（当前 `192.168.1.70:8000`，DHCP 变址需同步改 `config.js`）；手机与电脑同一 Wi-Fi；真机开发版勾选「不校验合法域名」。`recordings.status` 统一 `pending`（审核流转属阶段三）。

## 阶段二接口验证（真机实测）

微信登录 → 领任务 → 词条列表 → 逐条录音 → 上传 → 进度，**全链路已通**：

| 环节 | 验证内容 | 结果 |
|---|---|---|
| 微信登录 | `wx.login` code → `POST /api/mp/login` 换 openid/token（`WECHAT_APPID`/`WECHAT_SECRET` 已配）；登录自动把 `device_id` 与 openid 绑到同一 speaker 行 | ✅ |
| 领任务 | `GET /api/mp/tasks?province_code=` 只返回已发布任务，附 `word_count` / `recorded_count` | ✅ |
| 词条列表 | `GET /api/mp/tasks/{id}/words`，每条带 `recorded` / `recording_id` | ✅ |
| 上传身份 | 已登录上传自动带 Bearer token，后端按登录身份落库；无 token 仍回退 `device_id` | ✅ |
| 进度 | `GET /api/mp/recordings/progress?task_id=` 按状态计数（pending/approved/rejected） | ✅ |
| 后端守卫 | 未登录访问 → 401；任务未发布 → 400；任务不存在 → 404；code 无效 → 400「code 无效或已过期」 | ✅ |
| Secret 降级 | `WECHAT_SECRET` 为空时登录降级 `dev_<code>` 测试 openid，本地无网也能联调 | ✅ |

> `project.config.json` 的 AppID 已对齐登录凭据（`wx8aa4a30607982887`），保证 `jscode2session` 校验通过。

## 阶段三：录音审核（已实现）

后台「录音审核」页（`frontend` 的 `/review` 路由，菜单「任务分配」下）：**筛选 → 试听 → 转写（普通话/方言）→ 通过/驳回**，打通 `recordings.status` 的 `pending → approved / rejected` 流转。

| 环节 | 验证内容 | 结果 |
|---|---|---|
| 审核列表 | `GET /api/review/recordings?task_id=&status=&page=`，待审优先排序，富化任务名/词条/发音人/审核人 | ✅ |
| 试听 | 页面内原生 `<audio controls>` 播放 `/media/recordings/...`（前端 dev 已加 `/media` 代理） | ✅ |
| 通过 | `POST /api/review/recordings/{id}/verdict {approved:true}` → `status=approved`，写 `reviewed_by`/`reviewed_at` | ✅ |
| 驳回 | `{approved:false, note:"重录原因"}` → `status=rejected`，中文备注落库 | ✅ |
| 改判 | 对已审录音再提交判决 → 覆盖更新 | ✅ |
| 批量审核 | 勾选多条待审 → `POST /api/review/batch-verdict` 统一通过/驳回（只处理 pending，已审自动跳过，省管越省自动跳过） | ✅ |
| 列表筛选增强 | `keyword`（发音人/词条模糊）+ `province_code` 筛选 + `sort_by`（待审优先/提交时间/时长/审核时间） | ✅ |
| 驳回重置 | 已驳回录音一键 `POST /api/review/recordings/{id}/reset` 重置回待审（撤销判决、保留转写） | ✅ |
| 单条删除 | 已驳回坏录音 `DELETE /api/review/recordings/{id}` 清理（存储对象同步删除，发音人可重录） | ✅ |
| 转写 | 行内「转写」弹窗填普通话/方言转写（`PATCH /api/review/recordings/{id}/transcript`，缺省不改、空串清空），随数据集导出；发音人重录会清空转写 | ✅ |
| 省管理员权限 | `hebei_admin` 仅见/可审本省任务录音；越省 → 403 | ✅ |
| 小程序回流 | 审核后 `GET /api/mp/recordings/progress` 的 `approved`/`rejected` 计数自动更新 | ✅ |
| 守卫 | 无 token → 401；录音不存在 → 404；非法 status → 422 | ✅ |

> 发音人重录同名词条会覆盖录音并重置为 `pending`（复用阶段二覆盖策略），再次进入待审队列。后端 `python -c "from app.main import app"` 与前端 `npm run build` 均通过。

### 阶段四：数据集导出（已实现）

后台「录音审核」页新增「导出已通过数据集」按钮 → `GET /api/review/export` 把 **approved 录音**批量打成 ZIP 下载：音频按**省+任务嵌套归档**（`audios/{省份码}/task_{任务ID}/…`）+ `manifest.csv`（`utf-8-sig` BOM，Excel 可直接打开，含任务/词条/**词条元数据（方言点·例句·发音提示·备注）**/**转写文本列（普通话·方言）**/发音人/**性别年龄段中文列**/时长/审核时间等列）。支持按任务筛选，省管理员仅能导出本省任务；无已通过录音时返回 400「没有符合条件的已通过录音」。

### 阶段五：发音人画像采集（已实现）

小程序首页新增「个人信息」卡片采集**性别（男/女/其他）**与**年龄段（<18/18-30/31-45/46-60/>60）**：登录 + 录音上传均附带画像字段（后端**空不覆盖**落库），并支持 `POST /api/mp/profile` 自助修改（空串清空）。首次登录画像缺失时卡片**自动展开引导（可跳过）**。画像随 approved 录音进入数据集导出 manifest（`speaker_gender`/`speaker_age_bracket` 列）。DB：`speakers` 表新增 `gender`（varchar10）/`age_bracket`（varchar20），存量库用幂等 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 迁移。

### 阶段六：发音人管理（后台，已实现）

管理后台新增「发音人管理」页（`frontend` 的 `/speakers` 路由，侧边栏「录音审核」下）：**分页列表 + 筛选（省份 / 关键词：昵称·设备ID·openid / 性别 / 年龄段）+ 编辑发音人画像（性别/年龄段）+ 删除发音人（仅无录音，连带清理领取/协议/头像）**，行内显示**录音数**（`recording_count` 聚合）；**「明细」弹窗查看单个发音人的录音列表（含试听）+ 审核状态分布（待审/已通过/已驳回）+ 贡献统计（总录音 / 总时长 / **有效时长（审核通过）/ 无效时长（驳回）** / 按任务分布）**。后端 `GET /api/speakers`（分页筛选、省隔离、`recording_count`）+ `PATCH /api/speakers/{id}`（编辑画像，null/空串清空、非法值 422）+ `DELETE /api/speakers/{id}`（删除，有录音 400）+ `GET /api/speakers/{id}/recordings`（明细列表 + 统计，含 `stats.approved_duration_ms` / `rejected_duration_ms`）。省管理员**仅见/可改/可删本省**发音人（`province_code` 隔离），超管看全国。

### 阶段七：任务管理完善 + 发音人时长统计导出（已实现）

「任务分配」页对**已创建任务**补齐管理操作：草稿可**编辑**（名称/说明/必录数 + 词条整体替换）、**发布**；**任意状态（草稿/已发布/已关闭）可删除**（连带词条关联与领取记录，已有录音拒绝）；已发布可**关闭**（小程序端不再展示该任务，录音保留）；已关闭可**重新打开**（回到 published，小程序端恢复展示、可继续采录，录音保留）；任意状态可**查看词条清单**；列表补分页。后端新增 `PATCH /api/tasks/{id}`（编辑，仅草稿）+ `POST /api/tasks/{id}/close`（关闭，仅已发布）+ `POST /api/tasks/{id}/reopen`（重新打开，仅已关闭）+ `DELETE /api/tasks/{id}`（删除，任意状态，已有录音 400）+ `GET /api/tasks/{id}/words`（词条清单）。**选词区**完善**多页显示 + 跨页全选**：分页可选每页 20/50/100/200，勾选状态跨页保留（`reserve-selection`）；新增「全选当前页」与「跨页全选」（抓取当前筛选下全部分页词条一键选中，已选计数实时显示）。

**词条占用制**（选过任务的词条不可再选）：词条进入任一**草稿/已发布**任务即被**占用**——后台选词列表置灰 + 「已占用」标签、跨页全选自动跳过、后端 `POST/PATCH /api/tasks` 加占用守卫（直接连 API 也拦，400「已被其它任务占用」）；**任务关闭后词条释放回池**可再选；编辑草稿任务时排除自身词条（自己的词条合法）。`GET /api/words` 新增 `occupied` 字段与 `exclude_task_id` 参数。

「发音人管理」新增两个 **CSV 导出**（`utf-8-sig`，Excel 直接打开中文不乱码）：`GET /api/speakers/export`（发音人**时长汇总**，遵循列表筛选，每人一行含总时长/有效时长/无效时长）+ `GET /api/speakers/{id}/recordings/export`（单发音人**录音明细**，遵循任务/状态筛选）。时长列均为**毫秒整数**（与 `audio_duration` 一致，无舍入误差）。

### 阶段八·A：团队绑定属地隔离（省+市，已实现）

**目标**：发音人**什么地方的只能录什么地区的语音**——不是本地区的任务既**不能录也看不到**。

**方案（团队码绑定，一码一区）**：
- 管理后台新增「**团队管理**」页（`/teams` 路由）：每个团队码唯一绑定**一个省+市**（`UNIQUE(province_code, city_code)`），发音人输入团队码即锁定属地；只能**改名**，改区域/改码需删除重建；删除后已绑定发音人属地保留。省管理员仅能管理本省团队码（越省 403）。
- 小程序端：登录完成步骤未绑定则**必填团队码**（`POST /api/mp/team/join`），绑定后**不可更换**（需后台纠错）；首页「未加入团队」提示条 + 绑定弹窗；任务/画像/我的页属地**只读**展示「省·市」。

**服务端强制隔离（客户端无法绕过）**：
| 接口 | 未绑定 | 跨区 |
|---|---|---|
| `GET /api/mp/tasks` | 空列表 `{total:0}` | 服务端按省+市过滤，根本不返回 |
| `GET /api/mp/tasks/{id}/words` | `400 请先加入团队` | `403 该任务不属于你所在地区` |
| `POST /api/mp/recordings` | `400 请先加入团队` | `403 只能上传本团队所属地区的任务` |

任务列表只返回 `province_code==属地省` 且 `city_code==属地市` 的已发布任务；市级任务不投省级。

**发音人属地纠错**（「发音人管理」编辑弹窗）：管理员可改发音人省+市（省管理员仅限本省、不能越省改；可给本省「未绑定」发音人补属地），**改属地自动清空 `team_code`**（原绑定作废，发音人可重新绑定/后台重定属地）；列表新增「属地」「团队码」列。

**DB**：`speakers` 新增 `city_code`/`team_code`；新建 `team_codes` 表（`code` 大写唯一 + 一码一区约束）。幂等迁移：`backend/scripts/migrate_speaker_region.py`。**前端登录/上传不再接收 `province_code`**——属地唯一来源是团队码绑定。

**任务分配关联团队码**（「任务分配」页，阶段八·C）：创建/编辑任务可**关联团队**——选团队后**投放区划由团队码自动带出**（省+市随团队属地锁定，区县清空），列表新增「关联团队」列。团队码不存则 422；省管理员只能关联本省团队（403）；地区与团队不一致 422。`task_batches` 新增 `team_code`（幂等迁移 `backend/scripts/migrate_task_team_code.py`）。**关联仅作归属追溯/筛选，小程序端隔离仍按省+市**（团队码不改变任务可见性规则）。

### 阶段八·B：词条启用/禁用（已实现）

「词条库」页新增**状态开关**（启用/禁用）：禁用（下架）后该词条**不再出现在小程序任务词条列表、不可再采录**，但**已采集录音保留**（审核/导出/发音人明细不受影响）；可随时重新启用。词条库列表支持按状态筛选（全部/启用/禁用），「任务分配」选词与编辑草稿只可选**启用**词条。后端 `word_library.status`（`active` 默认 / `disabled`）+ `GET /api/words` 新增 `status` 筛选参数（非法值 422）+ `PATCH /api/words/{id}` 支持改 `status`；小程序 `GET /api/mp/tasks/{id}/words` 自动过滤禁用词条。存量库用幂等迁移脚本 `backend/scripts/migrate_word_status.py`（`ADD COLUMN IF NOT EXISTS` + 索引）。

### 阶段九：协议管理（已实现）

**三份合规协议**（用户协议 `user_agreement` / 隐私政策 `privacy_policy` / 声音单独授权协议 `voice_auth`），小程序登录时**三勾选全部同意才能登录**，后台可编辑（编辑 = 生成**不可变新版本**，发布后所有发音人需重新阅读同意）。

- **DB**：新建 `agreements`（协议版本表，`UNIQUE(type, version)`，种子三份 v1）+ `speaker_agreements`（发音人接受记录，`UNIQUE(speaker_id, type)`，先删后插幂等）。幂等迁移：`backend/scripts/migrate_agreements.py`。
- **后端强制拦截（客户端不可绕过）**：登录仍发 token（否则无法调同意接口），但未全部同意最新版前，所有功能接口（任务/词条/进度/上传/资料/头像）返回 `403 请先同意最新版用户协议、隐私政策与声音授权协议`；`upload_recording` 只拦登录身份、匿名 device_id 补传路径不拦。新接口：`GET /api/mp/agreements`（公开，最新三份）、`GET /api/mp/agreements/pending`（Bearer，我待确认的 type）、`POST /api/mp/agreements/accept`（Bearer，整体校验 + 旧版本 **409**「协议已更新，请重新阅读最新版本」，幂等/部分同意）。登录响应新增 `pending_agreements`。
- **管理后台**：新增「协议管理」页（`/agreements`，仅超管可见）：三类最新版本列表 + **编辑（生成新版本，保存前确认框提示所有发音人需重新同意）** + 历史版本弹窗。
- **小程序端**：登录页三行 checkbox + 协议名链接（点名字进 `pages/agreement/agreement` 滚动全文页），**三份全勾登录按钮才可点**；登录后 `pending_agreements` 非空弹**自定义确认窗**（列出待确认协议 + 「查看」+「同意并继续」，409 时提示「协议已更新」并刷新）；冷启动/后台升级后被 403 踢回登录页，`onLoad` 调 pending 接口**只弹被改的那份**。`utils/api.js` 收到协议守卫 403 自动 `wx.reLaunch` 回登录页。

### 阶段十一：任务词条领取制（多人采集互斥，已实现）

**领取制解决「多人同时采集同一词条」**：采集者主动领取 N 条后这 N 条归其**专有**（数据库级 `UNIQUE(task_id, word_id)` 兜底，并发也不会发给两个人），其他人不能领/不能录；未录可**自退**、管理后台可**解绑**；可**追加领取**（累计不超每人上限 `claim_limit`，默认 10）。

- **DB**：新建 `task_claims`（领取记录表，`UNIQUE(task_id, word_id)` 一词条一人 + 5 个索引）；`task_batches` 加 `claim_limit` 列；`task_batch_items` 去重并加 `UNIQUE(task_batch_id, word_id)`。幂等迁移：`backend/scripts/migrate_task_claims.py`（存量录音自动回填为领取，同词条多人录过只留一人，可超限祖父化，后台可解绑）。
- **后端**：新增 `POST/GET /api/mp/tasks/{id}/claims`（领取 / 我的统计，`SELECT ... FOR UPDATE` 锁任务行串行化并发）、`DELETE /api/mp/tasks/{id}/claims/{word_id}`（自退，已录 400）；`GET /api/mp/tasks/{id}/words` 改为**只返回我已领取**的词条；上传守卫**未领取 → 403**（属地校验之后、限流之前，不消耗配额）；管理端 `GET/DELETE /api/tasks/{id}/claims`（领取管理 / 解绑，已录 400）。
- **小程序**：任务卡/词条页「领取」按钮（选条数弹窗）+ 已领/可领进度（分母改为已领数）；词条页空池引导「先去领取」；本地队列把 403「未被你领取」标为「未领取」不当作普通错误重试。
- **管理后台**：任务表单加「每人领取上限」（默认 10）；任务列表加「领取」按钮 → 领取管理弹窗（词条/发音人/是否已录 + 解绑，已录禁用）。
- **回归**：新增 `backend/scripts/verify_task_claims.py`（进程内 22 项断言：未领上传 403 / 抢领 409 / 上限封顶 / 自退 / 后台解绑 / 并发 10 人抢 5 词条恰好 5×200 + 5×409）。

### 阶段十二：管理后台数据看板（已实现）

后台新增「**数据看板**」页（`/dashboard` 路由，侧边栏「发音人管理」下）：一页看平台/本省整体数据，并可下钻到**每一个发音人的详细数据**。

- **概览卡片 + 区域分布**：发音人总数 / 录音总数 / 待审核 / 已通过 / 已驳回 / 总时长 / 有效时长 / 通过率 + 活跃任务 / 团队数 / 已录词条 + **区域分布小表**（超管按省、省管理员按本省市级）。
- **录音趋势（数字卡片）**：概览卡片下「近 7 天 / 近 30 天」切换 → 新增录音 / 已通过 / 已驳回 / 通过率 4 张数字卡（`GET /api/dashboard/trends?days=`，窗口内按状态聚合，省管钳制）。
- **词条采集难度表**：概览下方独立卡片 —— 按词条聚合当前录音状态（录音总数 / 待审 / 通过 / 驳回 / 通过率 / 驳回率），定位「反复被驳回」的难采集词条；排序切换（按驳回数 / 按通过率 / 按录音数）+ 分页（`GET /api/dashboard/words`）。无审核历史表，用当前 `rejected` 计数近似（阶段五确认的「当前状态快照」口径）。
- **发音人明细表**（每发音人一行）：录音总数、待审/通过/驳回、总时长、有效时长、通过率、参与任务数、已录词条数、最近活跃、建档时间；筛选（关键词/省份/性别/年龄段/团队码）+ 5 种排序（录音数/通过数/时长/最近活跃/建档时间）+ 分页 + 导出时长 CSV。
- **详情下钻**：点「详情」弹窗 → 画像 + 状态统计卡（含任务分布）→「录音明细」tab（复用 `/speakers/{id}/recordings`，试听/筛选/导出）+「领取记录」tab（`/dashboard/speakers/{id}/claims`：词条/任务/是否已录）。
- **权限**：超管看全国；省管理员自动钳制为本省（发音人/录音/任务全部按 `province_code` 过滤）。
- **后端**：新增 `backend/app/routers/dashboard.py` + `schemas/dashboard.py`（`GET /api/dashboard/summary`、`GET /api/dashboard/speakers`、`GET /api/dashboard/speakers/{id}/claims`、`GET /api/dashboard/trends`、`GET /api/dashboard/words`，复用 `speakers.py` 的 `_speaker_query` 属地钳制与聚合模式）。
- **回归**：新增 `backend/scripts/verify_dashboard.py`（进程内 63 项断言：概览聚合「基线+增量」、省管钳制、明细行指标、5 种排序相对顺序、筛选/分页、领取记录、trends 近 7/30 天数字、词条难度快照/排序/省管钳制、越省 403 / 不存在 404）。

### 数据质量治理：词条查重 / 词条合并 / 发音人合并（后台完善项 4，已实现）

- **词条查重提示**：词条库编辑保存前调 `GET /api/words/check-duplicate?content=&exclude_word_id=`（全局精确匹配、排除自身）；命中弹「已存在相同内容词条 #id「content」」确认框，**仅提示不拦截**（确认后仍可保存 —— 方言词同词异音可能合法）。Excel 导入保持现状（批量补录逐行提示无意义）。
- **词条合并**：词条库操作列「合并」→ 搜索目标词条（编号/词条/方言点）→ 确认后 `POST /api/words/merge {keep, remove}`。引用迁移：Recording / TaskClaim / TaskBatchItem 的 word_id 并入 keep；录音同 `(task, speaker)` 冲突按状态保留策略去重（`approved>rejected>pending`，同级留新，淘汰者连带删除存储文件）；领取/任务条目冲突删除 remove 的（保持 `UNIQUE`）；删除 remove 词条。
- **发音人合并**：发音人管理操作列「合并」→ 搜索目标发音人（昵称/设备ID/openid）→ 确认后 `POST /api/speakers/merge {keep, remove}`（解决换设备/先匿名后微信登录产生的多身份）。引用迁移：Recording / TaskClaim / SpeakerAgreement 的 speaker_id 并入 keep；协议同 type 保留 version 大者（原地升级 keep 行，绕开 `UNIQUE(speaker_id, type)`）；属地/团队码以 keep 为准；remove 的 `device_id`/`openid` 置空后删除（绕过唯一约束）并清理头像文件。
- **后端**：`GET /api/words/check-duplicate`、`POST /api/words/merge`、`POST /api/speakers/merge`；`_pick_better_recording` 状态保留策略助手供两处合并共用。
- **回归**：新增 `backend/scripts/verify_word_merge.py`（进程内 28 项断言）与 `backend/scripts/verify_speaker_merge.py`（进程内 23 项断言）：查重命中/排除自身/空内容、引用迁移计数、录音冲突去重（含 remove 方胜出归 keep、不产生孤儿引用、淘汰者存储文件删除）、领取/条目/协议冲突、keep==remove 400、越省 403、合并后 remove 消失。

## 开发者工具打开方式

1. 微信开发者工具 →「导入项目」→ 选择 `miniprogram/` 目录。
2. `project.config.json` 已配好 AppID，直接编译即可。
3. **注意：开发者工具是模拟录音，无法产出真实 PCM**（工具会提示"录音文件与移动端格式不同"），
   PCM→WAV 转换和试听必须在**真机**上验证 —— 点工具栏「预览」→ 手机扫码。

> 真机录音需正式 AppID（已配）。真实上传联调：后端需监听 `0.0.0.0`（`uvicorn app.main:app --host 0.0.0.0 --port 8000`），
> 手机与电脑连同一 Wi-Fi，`miniprogram/utils/config.js` 的 `API_BASE` 填电脑局域网 IP；
> 真机/工具需开启「不校验合法域名」（开发版在右上角… → 开发调试 打开）。

## 验证 WAV 头（本环境可自动跑）

```bash
cd miniprogram/tools
node test_wav.js     # 生成 1s 16kHz 正弦 → out.wav，自检 44 字节头
python -c "import wave;w=wave.open('out.wav');print(w.getframerate(),w.getnchannels(),w.getsampwidth(),w.getnframes())"
# 期望：16000 1 2 16000
```

## 小程序对接契约

见 `docs/miniprogram-api.md`。已实现：微信登录 `POST /api/mp/login`、**协议三勾选 + 强制确认（阶段九）**、**团队绑定（属地=省+市）`POST /api/mp/team/join`**、领任务 `GET /api/mp/tasks`、词条列表 `GET /api/mp/tasks/{id}/words`、录音上传 `POST /api/mp/recordings`、任务进度 `GET /api/mp/recordings/progress`、**总体进度 `GET /api/mp/progress`**、省/市列表 `GET /api/mp/regions?parent_code=`、发音人画像 `POST /api/mp/profile`、**头像上传 `POST /api/mp/avatar`**、录音审核 `GET /api/review/recordings` + `POST /api/review/recordings/{id}/verdict`、数据集导出 `GET /api/review/export`、**我的录音时长统计与导出 `GET /api/mp/me/durations` + `GET /api/mp/me/export`**。**阶段八隔离**：任务/词条/上传按团队绑定属地（省+市）强制过滤，未绑定=空任务、跨区=403。**阶段九协议守卫**：未同意最新版三份协议前功能接口统一 403。

## 文档

- `docs/database.md` — 数据库表结构与字段含义（11 张表，含 speakers/team_codes/recordings/agreements/speaker_agreements）
- `docs/api.md` — 管理后台接口文档（含团队码管理 `/api/team-codes`、发音人属地纠错、协议管理 `/api/agreements`）
- `docs/miniprogram-api.md` — 小程序端对接契约（阶段一/二/三/八/九接口均已实现）
- `docs/deploy-guide.md` — 首次上线部署指南（建资源/域名/COS/systemd/Nginx）
- `docs/update-workflow.md` — **日常更新流程**（本地改完 → 同步后端/前端/小程序到线上，部署后每次改代码照着走）
- `docs/launch-check.md` — 小程序上线前真机手动验证清单

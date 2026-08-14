# 小程序端对接接口文档（精简版）

> 状态说明：阶段一（管理后台）+ 阶段二（小程序）+ 阶段三（录音审核）+ 阶段八（团队绑定属地隔离）+ 阶段九（三份协议登录确认）**已全部实现**——
>
> - **✅ 已实现**：登录 / **团队绑定（属地=省+市）** / 领任务 / 词条列表 / 录音上传 / 进度（任务内 + 总体）/ 省市区列表 / **头像上传（跨设备持久）** / **录音审核（试听·通过·驳回）** / **数据集导出（approved 录音批量导出）** / **我的录音时长统计与导出（`/api/mp/me/durations` + `/api/mp/me/export`）** / **三份协议（用户协议·隐私政策·声音单独授权协议）登录三勾选 + 版本升级重新确认**。
> - 已打通**「登录 → 协议确认 → 团队绑定 → 领任务 → 录 → 传 → 库 → 后台审核 → 进度 → 数据集导出」完整闭环**，真机端到端验证。
> - **阶段八 属地隔离（省+市，强制）**：发音人凭**团队码**（`POST /api/mp/team/join`）绑定省+市属地，绑定后只能看到/录制**本地区**任务——服务端按 `province_code+city_code` 严格过滤任务列表、词条、上传，客户端无法绕过；未绑定团队的任务列表为空、无法上传。
> - **阶段九 协议确认（后端强制）**：登录仍发 token，但未全部同意最新版**用户协议 + 隐私政策 + 声音单独授权协议**前，所有功能接口（任务/词条/上传/进度/资料等）返回 `403 请先同意最新版用户协议、隐私政策与声音授权协议`；后台发布新版本后需**重新阅读并同意**方可继续（详见 §协议确认）。

---

## 1. 通用约定

| 项 | 值 |
|---|---|
| Base URL | 生产域名 + `/api`（开发者工具联调 `http://127.0.0.1:8000`；真机联调 `http://<电脑局域网IP>:8000`，本机当前 `http://10.213.227.166:8000`） |
| 数据格式 | JSON（录音上传为 multipart） |
| 鉴权 | 小程序登录后携带 `Authorization: Bearer <token>`；上传接口**无 token 时回退 `device_id`**（兼容未登录补传） |
| 错误格式 | `{"detail": "<原因>"}`；422 为参数校验失败；**409 = 协议版本冲突**（§协议确认） |
| 协议守卫（阶段九） | 除 `POST /api/mp/login`、`GET /api/mp/agreements`、`POST /api/mp/agreements/accept`、`GET /api/mp/agreements/pending`、`GET /api/mp/regions` 外，其余需 Bearer 的功能接口在未同意最新版协议时统一返回 **`403 {"detail": "请先同意最新版用户协议、隐私政策与声音授权协议"}`** |

**小程序用户（发音人）与后台管理员是两套身份体系**：管理员登录用 `username+password`；小程序用户用微信 `wx.login` 的 code 换 openid（`POST /api/mp/login`）。登录时自动把 `device_id` 与 openid 绑定到同一 speaker 行，避免与历史 `device_id` 上传分叉。

**属地（省+市）与登录解耦**：登录/上传不再回填省份，属地**唯一来源是团队码绑定**（§2.1）。未绑定 = 任务列表为空 + 无法上传。

---

## 2. 登录

### ✅ 小程序登录 `POST /api/mp/login`（已实现）

微信 `wx.login()` 拿到临时 code 后换取 token，首次登录自动建档，并把 `device_id` 与 openid 绑定统一身份。

```
POST /api/mp/login
Content-Type: application/json

{
  "code": "0a1Xc...",
  "device_id": "dev_xxx",      // 可选，用于与历史 device_id 录音身份统一
  "nickname": "张老师",        // 可选
  "gender": "female",          // 可选，画像：male/female/other
  "age_bracket": "age31_45"    // 可选，画像：under18/age18_30/age31_45/age46_60/over60
}
```

> 注意：**无 `province_code` 字段**——属地（省+市）由团队码绑定决定（§2.1），登录不接收、不回填。

**响应 200**：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "speaker": {
    "id": 1,
    "openid": "oXk...",
    "nickname": "张老师",
    "avatar_url": "https://thirdwx.qlogo.cn/mmopen/...",
    "province_code": "13",
    "city_code": "1301",
    "team_code": "HB-SJZ",
    "gender": "female",
    "age_bracket": "age31_45",
    "created_at": "2026-08-07T09:00:00Z"
  },
  "pending_agreements": ["user_agreement", "privacy_policy", "voice_auth"]
}
```

> `pending_agreements`（阶段九）：尚未同意最新版协议的 type 数组，空 `[]` = 三类已全部同意。非空时小程序端需弹**协议确认窗**（§2.2），全部同意后方可继续使用功能接口。

- 后端用 `code` 调微信 `jscode2session` 换 `openid`（`WECHAT_APPID`/`WECHAT_SECRET` 已配置）。
- **开发兜底**：`WECHAT_SECRET` 未配置时，`code` 直接映射为 `dev_<code>` 的测试 openid，便于本地联调。
- 首次登录自动建档（`nickname`/`avatar_url` 落库）；再次登录按 openid 复用同一 speaker，并回填昵称/画像（**空不覆盖**已有值）。
- 响应含 `province_code`/`city_code`/`team_code`（团队码绑定后才有值，未绑定三者皆空，见 §2.1）。
- 小程序端为**强制登录门禁**：登录页 `wx.login` 静默换 token（不弹授权窗）→ 登录成功后进入「完善资料」步骤（官方**头像昵称填写**能力：`open-type="chooseAvatar"` 按钮 + `type="nickname"` 输入框 + **性别/年龄段选择器**，均可跳过），保存时 `POST /api/mp/profile` 提交（头像昵称 + 画像一并落库）；拒绝跳过则昵称默认「微信用户」、头像/画像为空，可在「我的」页随时补。**注意**：`wx.getUserProfile` 自 2022 年起受微信隐私政策限制，无法稳定返回真实昵称/头像，不再使用。
- 画像值域：`gender` = `male/female/other`；`age_bracket` = `under18/age18_30/age31_45/age46_60/over60`（非法值 422）。
- 错误：`400 {"detail": "code 无效或已过期"}`、`502 微信登录服务暂不可用`。
- 之后的读接口统一带 `Authorization: Bearer <access_token>`。

### ✅ 加入团队（绑定属地） `POST /api/mp/team/join`（已实现，需 Bearer）

发音人凭**团队码**绑定省+市属地（阶段八核心入口）。团队码由后台「团队管理」页创建，**一码一区**（每个码唯一对应一个省+市）。绑定后属地锁定：

```
POST /api/mp/team/join
Authorization: Bearer <access_token>
Content-Type: application/json

{ "code": "HB-SJZ" }
```

- 团队码不区分大小写（后端统一转大写匹配）；未找到 → `404 {"detail": "团队码不存在或已停用"}`。
- 绑定成功 → **响应 200**：更新后的 `speaker`（`province_code`/`city_code`/`team_code` 均被写入，如 `13`/`1301`/`HB-SJZ`）。
- **绑定后不可更换**：再次 join → `400 {"detail": "已绑定团队（HB-SJZ），无法更换；如需修改请联系管理员"}`（后台管理员可「发音人属地纠错」改属地，改后 `team_code` 自动清空，发音人可重新绑定）。
- 未登录 → 401。

**小程序端 UX**：登录完成步骤若未绑定则**必填团队码**（输入框，保存时一并 join）；已绑定用户直接进首页；首页顶部「未加入团队」提示条 → 点击弹**自定义绑定弹窗**（`pages/index`）：卡片式 dialog + 品牌风格输入框（自动**转大写**、聚焦高亮、限长 32）+ 绑定 loading + 完整错误弹窗（绑定成功 toast）。

### ✅ 更新个人资料 `POST /api/mp/profile`（已实现，需 Bearer）

发音人自助更新**头像昵称 + 性别年龄段**，**明确意图直接覆盖**（与登录/上传的空不覆盖不同）。

```
POST /api/mp/profile
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "gender": "female",
  "age_bracket": "age31_45",
  "nickname": "李方言",
  "avatar_url": "https://thirdwx.qlogo.cn/mmopen/..."
}
```

- `gender` / `age_bracket` / `avatar_url` 均可省略（`null`/缺省 = **不改**）；空串 `""` = **清空**该字段（性别/年龄段/头像）；非法值 422。
- `nickname` 仅**非空**才更新（昵称列不可为空，空串/缺省 = 不改）。
- **响应 200**：更新后的 `speaker` 对象（同登录响应结构）。
- 未登录访问 → 401。

### ✅ 上传头像 `POST /api/mp/avatar`（已实现，需 Bearer，multipart）

`open-type="chooseAvatar"` 得到的本地临时头像路径对其它设备无效，小程序先把图片上传到服务器，换回 `/media/avatars/...` 持久路径，再随资料更新存储 `speaker.avatar_url`。

```
POST /api/mp/avatar
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file: <图片文件>
```

- 支持 `.jpg/.jpeg/.png/.webp/.gif`，限 2MB；按魔数校验真实图片（伪装扩展名 → 400「文件不是有效图片」）。
- 落盘 `backend/media/avatars/{speaker_id}_{随机}.{ext}`，`speaker.avatar_url` 更新为 `/media/avatars/...`；替换旧头像时自动删除原服务器文件。
- **响应 200**：更新后的 `speaker` 对象（`avatar_url` 为服务器路径）。
- 未登录 → 401；扩展名不支持 / 空文件 / 超 2MB / 非图片 → 400。
- 小程序端 `utils/speaker.js`：`ensureAvatarUrl(本地路径)` 封装「本地临时 → 上传 → 服务器 URL」转换；头像展示用 `getAvatarDisplayUrl()`（`/media` 开头自动拼 `API_BASE`）。登录页 / 「我的」页保存头像时均走此链路。

### ✅ 协议确认（阶段九）

**三类协议**（后台「协议管理」页可编辑，`docs/api.md` §11）：`user_agreement` 用户协议 / `privacy_policy` 隐私政策 / `voice_auth` 声音单独授权协议。稳定 type 字符串、最新版本由服务端统一管理；发布新版本（version 递增）后所有发音人需重新同意。

#### 获取三类协议最新版本 `GET /api/mp/agreements`（公开，无需登录）

```
GET /api/mp/agreements
```

**响应 200**：3 条，按 `user_agreement / privacy_policy / voice_auth` 顺序。

```json
[
  { "type": "user_agreement", "title": "用户协议", "version": 1, "content": "《方言采集平台用户协议》…" },
  { "type": "privacy_policy", "title": "隐私政策", "version": 1, "content": "…" },
  { "type": "voice_auth", "title": "声音单独授权协议", "version": 1, "content": "…" }
]
```

#### 我尚未同意的协议 `GET /api/mp/agreements/pending`（需 Bearer）

```
GET /api/mp/agreements/pending
Authorization: Bearer <access_token>
```

**响应 200**：`{"pending_agreements": ["user_agreement"]}`（空数组 = 全部已同意）。用于冷启动/版本升级后登录页判定"只弹被改的那份"。

**错误**：401 未登录。

#### 提交同意 `POST /api/mp/agreements/accept`（需 Bearer）

```
POST /api/mp/agreements/accept
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "accepted": [
    { "type": "user_agreement", "version": 1 },
    { "type": "privacy_policy", "version": 1 },
    { "type": "voice_auth", "version": 1 }
  ]
}
```

- **整体校验**：每个 type 必须合法（否则 422）；`(type, version)` 必须等于该 type 的**当前最新版本**——提交旧版本 → **`409 {"detail": "协议已更新，请重新阅读最新版本"}`**（不写库，小程序端需重新拉取并展示最新版）。
- **幂等**：重复同意是 no-op；允许**部分同意**（只提交已阅读的那份，其余下次再提交）。
- 写库策略：对 `(speaker_id, type)` 先删后插（保持每人每类仅一条接受记录）。
- **响应 200**：`{"pending_agreements": [...]}`（空 = 全部已同意，可进入后续功能）。
- **错误**：401 未登录；422 非法 type / `accepted` 为空；409 版本已更新。

**后端强制拦截（不可绕过）**：同意提交前，所有功能接口（任务/词条/进度/上传/资料/头像等）返回 `403 {"detail": "请先同意最新版用户协议、隐私政策与声音授权协议"}`。`upload_recording` 仅拦**登录身份**（Bearer），匿名 `device_id` 补传路径不拦。小程序端 `utils/api.js` 收到该 403 自动 `wx.reLaunch` 回登录页重新确认。

**小程序端 UX（`pages/login` + `pages/agreement`）**：
- 登录页预登录块：三行 `checkbox` + 协议名链接（点名字 `navigateTo` 到 `pages/agreement/agreement?type=xxx` 滚动全文页）；**三份全部勾选**登录按钮才可点（`disabled="{{!allChecked || loading}}"`），未全勾 onLogin 内 toast 拦截。
- 登录成功后 `pending_agreements` 非空 → 弹**自定义确认弹窗**（列出待确认协议标题 + 版本 + 「查看」链接），「同意并继续」提交弹窗内的版本；409 → toast「协议已更新，请重新阅读」→ 重新拉取最新协议与 pending，保持弹窗。
- 冷启动/后台升级协议后旧用户被 403 踢回登录页 → `onLoad` 调 `GET /api/mp/agreements/pending` 判定，只弹被改的协议；全部同意后进首页。

---

## 3. 任务（领任务）

### ✅ 我的可用任务 `GET /api/mp/tasks`（已实现）

登录后拉取**本地区（团队码绑定的省+市）**已发布任务（需 `Authorization: Bearer <token>`）。

```
GET /api/mp/tasks?page=1&page_size=20
```

> **阶段八隔离（服务端强制）**：任务列表只返回 `province_code == 发音人属地省` **且** `city_code == 属地市` 的已发布任务。**不再接受任何客户端区域参数**（`province_code`/`city_code`/`district_code` 查询参数已移除）；未绑定团队 → `{"total": 0, "items": []}`。

**响应 200**：

```json
{
  "total": 2,
  "items": [
    {
      "id": 1,
      "name": "河北省核心词任务",
      "description": "第一批发音任务",
      "province_code": "13",
      "city_code": null,
      "district_code": null,
      "required_audio_count": 30,
      "claim_limit": 10,
      "my_claimed": 3,
      "claimable": 7,
      "available": 20,
      "status": "published",
      "word_count": 35,
      "recorded_count": 12,
      "rejected_count": 2
    }
  ]
}
```

- `status` 只返回 `published`；`recorded_count` 为当前用户在该任务的已录条数（去重词条，含待审/已通过/被驳回）；`rejected_count` 为其中被驳回需重录的词条数（用于任务卡提示）。
- **阶段十一领取字段**：`claim_limit` 每人领取上限；`my_claimed` 我已领取数；`claimable` 我还能领多少（= `max(0, min(claim_limit - my_claimed, available))`）；`available` 任务剩余未领条数。任务卡「领取」按钮按 `claimable` 启用。
- 任务卡**进度条以「已领词条数」为目标**：`percent = min(100, round(recorded_count / max(my_claimed, recorded_count) × 100))`，文案「已录 X / 已领 N 条」；领取制之前的存量录音兜底取大（进度不倒退）。
- **已关闭（closed）任务不展示**：后台可 `POST /api/tasks/{id}/close` 下架任务，小程序端该任务即刻从列表消失，已采集录音保留；后台可 `POST /api/tasks/{id}/reopen` 重新打开，任务回到 published 后即刻恢复展示。
- **市级任务不投省级**：仅发布到指定市的市级任务（`city_code` 非空），只对该市绑定发音人可见；未发布到该市的省/区任务对发音人不可见。

### ✅ 后台任务列表（可复用只读） `GET /api/tasks`

带管理员 token 可分页查所有任务（含 `status` 筛选）。小程序端一般不直接用，联调期可借用验证数据。

---

## 4. 词条（录音内容）

### ✅ 任务词条列表 `GET /api/mp/tasks/{task_id}/words`（已实现）

登录后拉取某任务**我已领取**的词条（领取制，阶段十一），供发音人逐条朗读。**一条没领 → 空列表 + `claim` 可领数**（引导先领取）。

```
GET /api/mp/tasks/1/words
```

**响应 200**：

```json
{
  "task": { "id": 1, "name": "河北省核心词任务", "required_audio_count": 30 },
  "total": 2,
  "items": [
    {
      "word_id": 1,
      "code": "HB-001",
      "content": "咋整",
      "example_sentence": "这事咋整啊？",
      "pronunciation_hint": "zǎ zhěng",
      "remark": "核心词",
      "mandarin_transcript": "这事咋整啊？",
      "dialect_transcript": "zà zěng zua",
      "recorded": true,
      "recording_id": 101,
      "status": "approved"
    }
  ],
  "claim": {
    "task_word_total": 35,
    "claim_limit": 10,
    "my_claimed": 2,
    "claimable": 8,
    "available": 20,
    "my_claim_word_ids": [1, 2]
  }
}
```

- 仅 `published` 任务可拉取（草稿返回 `400 任务未发布`）。
- **阶段八隔离**：未绑定团队 → `400 请先加入团队（输入团队码）后再操作`；任务不属于发音人属地（省+市任一不符）→ `403 该任务不属于你所在地区`（防止通过任务 ID 越权查看/录制）。
- **仅返回「我已领取」且启用（`active`）的词条**：后台可将词条置为 `disabled` 下架（如词条有问题需修正），下架后该词条从任务列表消失、不可再录；已采集录音保留。后台开关接口见 `docs/api.md` §4.2。
- `claim` 为领取统计（词条池视角），同 `GET /api/mp/tasks/{task_id}/claims`。
- `status` 为当前发音人该词条最新录音的审核状态：`pending`（待审核）/ `approved`（已通过）/ `rejected`（需重录）；未录为 `null`。小程序据此渲染：
  - `rejected` → 红色「需重录」标签，提示发音人重录；
  - `approved` → 绿色「已通过」；`pending` → 橙色「待审核」；
  - 重录上传会覆盖旧录音并重置为 `pending`（覆盖策略见 §5）。
- `mandarin_transcript` / `dialect_transcript`：**审核页填写的转写**（普通话/方言），取自该词条最新录音。小程序对「已通过且有转写」的词条展示转写参考块（参考发音，重录后随覆盖清空）；未录/无转写为 `null`。

### ✅ 领取制：领取 / 我的领取统计 / 自退（阶段十一·已实现）

> **领取制保证多人采集互斥**：主动领取 N 条后这 N 条**归你专有**，其他人不能领/不能录；未录可自退、后台可解绑（`docs/api.md` §6.9/6.10）；可追加领取（累计不超 `claim_limit`）。三个接口均需 `Authorization: Bearer <token>`，可见性规则同 `/words`（published + 属地/演示隔离）。

#### 我的领取统计 `GET /api/mp/tasks/{task_id}/claims`

**响应 200**（`MpClaimStats`，词条池视角）：

```json
{
  "task_word_total": 35,
  "claim_limit": 10,
  "my_claimed": 3,
  "claimable": 7,
  "available": 20,
  "my_claim_word_ids": [1, 2, 3]
}
```

#### 领取词条 `POST /api/mp/tasks/{task_id}/claims`

**请求体**二选一（`count` 与 `word_ids` 都传时优先 `word_ids`）：

```json
{ "count": 10 }                    // 自动按 word_id 取前 N 条（不越池、不超上限）
{ "word_ids": [1, 2, 3] }          // 精确领取；任一不可领 → 整单 409
```

**响应 200**：

```json
{ "claimed_word_ids": [1, 2, 3], "stats": { /* 同 GET /claims */ } }
```

**错误**：
- `422`：`count` 与 `word_ids` 二选一且必填 / `count < 1` / `word_ids` 存在重复
- `409 {"detail": "部分词条不可领取（已领/不属于本任务/超上限）"}`（word_ids 模式有任一不可领，整单回滚）
- `409 {"detail": "当前无可领取词条或已达领取上限"}`（count 模式可领为 0）

> 并发安全：服务端 `SELECT ... FOR UPDATE` 锁任务行串行化领取，同一词条不会发给两个人；`UNIQUE(task_id, word_id)` 为最终防线。

#### 自退未录词条 `DELETE /api/mp/tasks/{task_id}/claims/{word_id}`

已领取但**未录制**的词条退回池子（别人可再领）；**已录不可退**。

**响应 200**：`MpClaimStats`（退回后最新统计）

**错误**：
- `404 {"detail": "该词条未被你领取"}`
- `400 {"detail": "已录制不能退回"}`

### ✅ 后台词条列表（可复用只读） `GET /api/words`

支持 `province_code/city_code/district_code/keyword` 筛选 + 分页，联调期可借用验证词库数据。

---

## 4.5 行政区划

### ✅ 省列表 `GET /api/mp/regions`（已实现）

不传参返回全部一级区划（省）。

### ✅ 市列表 `GET /api/mp/regions?parent_code={province_code}`（已实现）

传 `parent_code` 返回归属该省的二级区划（市）；父区划不存在 → `404`。

- 响应为 `[{ "code": "13", "name": "河北省", "level": 1 }]` 列表；`code` 即 adcode。
- 小程序端 `utils/region.js` 封装缓存：`getProvinces()` / `getCities(provinceCode)`；`regionText(provinceCode, cityCode)` → `省·市`（如 `辽宁·沈阳`），供「我的 / 画像」只读展示属地。团队码绑定后属地为只读，无前端选择器（服务端强制隔离）。

---

## 5. 录音上传

### ✅ 上传录音 `POST /api/mp/recordings`（已实现）

multipart/form-data 一次上传一条。**已登录优先按 token 身份落库**（`Authorization` 头），未登录回退 `device_id` 识别发音人（兼容补传）。

```
POST /api/mp/recordings
Content-Type: multipart/form-data

task_id:        1
word_id:        3
duration:       2400      // 录音时长（毫秒，后端存 audio_duration 秒亦可）
device_id:      dev_xxx   // 备选身份；已登录时可不带
nickname:       张老师    // 可选，首次建档时写入
gender:         female    // 可选，画像 male/female/other（未登录建档时写入，空不覆盖）
age_bracket:    age31_45  // 可选，画像（同上）
file:           <音频文件>
```

> 注意：**无 `province_code` 表单字段**——属地由团队码绑定决定（§2.1），上传不接收、不回填。

**响应 200**：

```json
{
  "recording_id": 101,
  "audio_url": "/media/recordings/13/1_3_101.wav",
  "status": "pending",
  "speaker_id": 5,
  "overwritten": false
}
```

**后端校验与行为**：

- `task_id` 对应任务必须存在（否则 `404 任务不存在`）且已发布（否则 `400 任务未发布`）。
- `word_id` 必须属于该任务（否则 `400 词条不属于该任务`）。
- **阶段八隔离**：未绑定团队 → `400 请先加入团队（输入团队码）后再操作`；任务非本团队属地（省+市任一不符）→ `403 只能上传本团队所属地区的任务`。**本地区任务才能上传**。
- **阶段十一领取守卫**：词条须为**本人已领取**（`task_claims` 有记录）否则 `403 该词条未被你领取，请先在任务页领取`。该 403 在属地校验之后、上传限流之前，**不消耗限流配额**（小程序本地队列会把此类项标记为「未领取」而非普通错误重试）。
- 音频扩展名限 `.wav` / `.mp3` / `.m4a` / `.aac`；空文件返回 `400 录音文件为空`。
- 同一 `(task_id, word_id, speaker_id)` 已存在录音时：**覆盖**旧录音（删除旧文件、保持 recording id、状态重设为 `pending`），响应 `overwritten: true`。
- 文件落盘到 `backend/media/recordings/{task_id}/{task_id}_{word_id}_{speaker_id}{ext}`，`audio_url` 可直接拼接 `/media` 静态服务试听。

---

## 6. 录音进度

### ✅ 我的进度 `GET /api/mp/recordings/progress?task_id=1`（已实现）

登录后查看当前发音人在指定任务的进度（需 `Authorization: Bearer <token>`）。

**响应 200**：

```json
{
  "task_id": 1,
  "total_words": 35,
  "recorded": 12,
  "pending": 10,
  "approved": 1,
  "rejected": 1
}
```

- 小程序首页可据此显示"完成 xx / 35"的进度条。
- `pending` = 已录待审核；`approved` = 审核通过（可不再重录）；`rejected` = 未通过（需重录）。

### ✅ 我的总体进度 `GET /api/mp/progress`（已实现，需 Bearer）

跨任务汇总当前发音人的录音审核进度（首页「审核进度」卡片）。

**响应 200**：

```json
{
  "recorded": 42,
  "pending": 30,
  "approved": 9,
  "rejected": 3
}
```

- `recorded` = `pending + approved + rejected`（已录总数）。
- `pending` = 待审核；`approved` = 已通过；`rejected` = 需重录（已驳回）。
- 未登录 → 401。

### ✅ 我的录音时长统计 `GET /api/mp/me/durations`（已实现，需 Bearer）

当前发音人**全部任务**录音时长统计（「我的 → 导出录音时长」预览用）。时长均为**毫秒整数**。

**响应 200**：

```json
{
  "total_count": 12,
  "total_duration_ms": 610000,
  "pending_count": 3,
  "pending_duration_ms": 120000,
  "approved_count": 7,
  "approved_duration_ms": 350000,
  "rejected_count": 2,
  "rejected_duration_ms": 140000
}
```

- `approved_duration_ms` = 有效时长（审核通过）；`rejected_duration_ms` = 无效时长（被驳回）。
- `total_duration_ms` = `pending + approved + rejected`（毫秒整数相加，无舍入误差）。
- 未登录 → 401。

### ✅ 导出我的录音时长明细 `GET /api/mp/me/export`（已实现，需 Bearer）

导出当前发音人自己的全部录音明细 CSV（`utf-8-sig` BOM，Excel 直接打开中文不乱码），列与后台发音人明细导出一致：`录音ID / 任务 / 词条编码 / 词条内容 / 状态 / 时长_ms / 文件大小_B / 审核备注 / 审核时间 / 提交时间 / 音频路径`；状态为中文（待审核/已通过/已驳回）。

- 响应头：`Content-Disposition: attachment; filename="durations_export.csv"; filename*=UTF-8''我的录音时长_<时间戳>.csv`（中文名走 RFC 5987，`filename` 为 ASCII 兜底）。
- 小程序端：下载 → `wx.saveFile` 存本地 → `wx.shareFileMessage` 分享（发送到文件传输助手保存）；未登录 → 401。

---

## 7. 审核（已实现）

后台「录音审核」页：筛选 → 试听（`/media` 静态播放）→ 通过/驳回，打通 `recordings.status` 的 `pending → approved / rejected` 流转；省管理员仅可见/可审本省任务的录音。

### ✅ 录音列表 `GET /api/review/recordings`（已实现，需管理员 token）

```
GET /api/review/recordings?task_id=1&status=pending&keyword=张老师&province_code=13&sort_by=created&page=1&page_size=20
```

**响应 200**：

```json
{
  "total": 2,
  "items": [
    {
      "id": 101,
      "task_id": 1,
      "task_name": "河北省核心词任务",
      "word_id": 22,
      "word_code": "HB-001",
      "word_content": "咋整",
      "speaker_id": 5,
      "speaker_nickname": "张老师",
      "speaker_device": "dev_xxx",
      "audio_url": "/media/recordings/1/1_22_5.wav",
      "audio_duration": 2400,
      "file_size": 76844,
      "mandarin_transcript": null,
      "dialect_transcript": null,
      "status": "pending",
      "review_note": null,
      "reviewed_by": null,
      "reviewed_by_name": null,
      "created_at": "2026-08-07T09:00:00Z",
      "reviewed_at": null
    }
  ]
}
```

- **筛选**：`task_id`（任务）、`status`（仅 `pending`/`approved`/`rejected`，否则 422）、`keyword`（模糊匹配**发音人昵称/设备ID/openid 或词条内容/编号**）、`province_code`（任务所属省）。
- **排序** `sort_by`：`pending_first`（默认，待审优先 + `created_at` 倒序）| `created`（提交时间倒序）| `duration`（音频时长倒序）| `reviewed`（最近审核优先，未审靠后）。非法值 422。
- 分页 `page` / `page_size`（默认 20）；省管理员自动钳制为本省任务录音。
- `reviewed_by_name` 为审核管理员姓名；未审核项为 `null`。

### ✅ 批量审核 `POST /api/review/batch-verdict`（已实现，需管理员 token）

对多条录音**统一通过/驳回**（审核页勾选多条 → 批量操作）：

```
POST /api/review/batch-verdict
Authorization: Bearer <admin token>
Content-Type: application/json

{ "recording_ids": [101, 102, 103], "approved": true, "note": null }
```

- `recording_ids`：非空且全部存在（空 → 400「未选择任何录音」；有不存在的 → 404）。
- **只处理 `pending`**：已审过的自动跳过（不覆盖人工判决）；省管理员自动跳过非本省任务录音。
- `approved`：统一通过/驳回；`note`：统一驳回原因（可空）。
- **响应 200**：`{"processed": 2, "skipped": 1}` —— `processed` 实际改判数，`skipped` 已审/越省跳过数。若 `processed = 0` → `400「所选录音均无需审核」`。

### ✅ 审核判决 `POST /api/review/recordings/{recording_id}/verdict`（已实现，需管理员 token）

```
POST /api/review/recordings/101/verdict
Content-Type: application/json

{ "approved": true, "note": "口音标准，通过" }
```

- `approved: true` → `status=approved`；`false` → `status=rejected`；`note` 为审核备注（驳回原因，可空）。
- 响应为单条富化后的录音（同列表项结构）；录音不存在 → `404 录音不存在`。
- 允许重复审核（改判覆盖，`reviewed_by`/`reviewed_at` 更新）。
- 审核后：小程序进度接口（§6）的 `approved`/`rejected` 计数自动反映；发音人重录同名词条会覆盖并重置为 `pending`。

### ✅ 驳回重置为待审 `POST /api/review/recordings/{recording_id}/reset`（已实现，需管理员 token）

审核**误判驳回**后一键把录音重置回 `pending` 重新排队审核（审核页已驳回行「重置」按钮）：

```
POST /api/review/recordings/101/reset
Authorization: Bearer <admin token>
```

- **仅 `rejected` 可重置**：`pending`/`approved` → `400「仅已驳回的录音可重置为待审」`；不存在 → `404`；省管理员越省 → `403`。
- 重置内容：`status=pending`、清空 `review_note`/`reviewed_by`/`reviewed_at`（撤销上次判决）。
- **转写（普通话/方言）与内容安全标记保留**——只撤销判决，不清内容资产。
- 响应为重置后的单条富化录音。

### ✅ 单条删除录音 `DELETE /api/review/recordings/{recording_id}`（已实现，需管理员 token）

清理**已驳回的坏录音**（口音差/噪音/垃圾音频），审核页已驳回行「删除」按钮：

```
DELETE /api/review/recordings/101
Authorization: Bearer <admin token>
```

- **仅 `rejected` 可删**：`pending`/`approved` → `400「仅已驳回的录音可删除」`；不存在 → `404`；省管理员越省 → `403`。
- 删除时同步清理存储对象（COS 对象 / 本地文件，失败不阻断）+ 删除 DB 行。
- **领取记录保留**：删除后该 (任务, 词条, 发音人) 不再有录音，发音人可重新录制（进度接口的 `recorded` 自动变 false）。
- 响应 200：`{"detail": "已删除"}`。

### ✅ 更新录音转写 `PATCH /api/review/recordings/{recording_id}/transcript`（已实现，需管理员 token）

审核页为录音填写**普通话转写 / 方言转写**（转写文本列，随数据集导出）：

```
PATCH /api/review/recordings/101/transcript
Authorization: Bearer <admin token>
Content-Type: application/json

{ "mandarin_transcript": "这事咋整啊？", "dialect_transcript": "zà zěng zua" }
```

- `mandarin_transcript` / `dialect_transcript` 均可省略（缺省 = **不改**）；`null` 或空串 = **清空**该字段。
- 响应为更新后的单条富化录音（同列表项结构，含两个转写字段）。
- 录音不存在 → `404 录音不存在`；省管理员仅可改本省任务录音（越省 → `403`）；未登录 → 401。
- 与审核判决独立：通过/驳回前后均可填写；发音人**重录**同名词条会覆盖旧音频并**清空转写**（需重新填写）。

### ✅ 数据集导出 `GET /api/review/export`（已实现，需管理员 token）

批量导出**已通过（approved）**录音为 ZIP 下载：音频按**省+任务嵌套归档** `audios/{province_code}/task_{task_id}/{task_id}_{word_id}_{speaker_id}.wav` + `manifest.csv`（`utf-8-sig` BOM，Excel 可直接打开中文）。

```
GET /api/review/export?task_id=1
Authorization: Bearer <admin token>
```

**响应 200**：`application/zip` 附件（`Content-Disposition: attachment; filename=dialect_dataset_<时间戳>.zip`）。

`manifest.csv` 列：

| 列 | 说明 |
|---|---|
| recording_id | 录音 id |
| task_id / task_name | 所属任务 |
| province_code | 任务省份代码 |
| word_id / word_code / word_content | 词条 |
| word_dialect_point / word_example_sentence / word_pronunciation_hint / word_remark | 词条元数据：方言点 / 例句 / 发音提示 / 备注 |
| mandarin_transcript / dialect_transcript | 审核页填写的转写：普通话 / 方言（未填为空串） |
| speaker_id / speaker_nickname / speaker_device | 发音人 |
| audio_file | ZIP 内音频路径（`audios/{省}/task_{任务ID}/...`，文件缺失为空串） |
| audio_present | 1=有音频；0=缺失（缺失不阻断整体导出） |
| audio_duration_ms / file_size | 时长（毫秒）/ 文件大小（字节） |
| recorded_at / reviewed_at | 提交 / 审核时间（ISO） |

- 不传 `task_id` 导出全部已通过录音；传则仅导出该任务。
- **省管理员仅能导出本省任务的录音**（与审核列表同范围）。
- 无可导出录音 → `400 {"detail": "没有符合条件的已通过录音"}`；未登录 → 401。

完整数据流闭环：

```
小程序登录 → 领任务 → 逐条录音上传 → 后台试听审核（通过/驳回）→ 发音人看进度 → 合格录音数据集导出（ZIP + manifest.csv）
```

---

## 8. 数据表（已实现，详见 `database.md`）

| 表 | 字段要点 |
|---|---|
| `speakers`（发音人）✅ | id、device_id(unique,index)、openid(unique,index)、nickname、avatar_url、province_code(index)、**city_code(index)**、**team_code(index)**（阶段八：属地省+市 + 绑定团队码）、**gender**(male/female/other)、**age_bracket**(under18/age18_30/age31_45/age46_60/over60)、created_at |
| `recordings`（录音）✅ | id、task_id(index)、word_id(index)、speaker_id(index)、audio_url、audio_duration、file_size、status(`pending`/`approved`/`rejected`)、review_note、reviewed_by、created_at、reviewed_at、**mandarin_transcript**（普通话转写）、**dialect_transcript**（方言转写） |
| `team_codes`（团队码）✅ | id、code(unique,index,大写)、name、province_code(index)、city_code(index)、created_by、created_at。约束：`UNIQUE(code)`、`UNIQUE(province_code,city_code)`（**一码一区**） |
| `agreements`（协议版本）✅ | id、type(index)、title、version、content、updated_by、updated_at。约束：`UNIQUE(type, version)`——每行=某协议的一个**不可变版本** |
| `speaker_agreements`（发音人接受记录）✅ | id、speaker_id(index)、type、version、accepted_at。约束：`UNIQUE(speaker_id, type)`——每人每类仅一条接受记录（重同意先删后插） |

> 录音按 `task_id + word_id` 关联任务中的词条；`rms_energy`（音量能量）可在录音时由小程序端采集随上传附带，供审核参考（可选字段，暂未实现）。

---

## 9. 小程序端对接 Checklist

1. ✅ 后端 `speakers`、`recordings` 两表 + `POST /api/mp/recordings`（device_id 身份，无需 AppID）。
2. ✅ 录音文件静态服务 `/media`（`backend/media/`，由 FastAPI StaticFiles 挂载）。
3. ✅ 小程序端：`utils/config.js` 配 `API_BASE`、`utils/speaker.js` 生成稳定 `device_id`、`uploader.js` `USE_MOCK=false`，队列「一键提交/自动补传」走真实 `wx.uploadFile`。
4. ✅ 微信登录 `POST /api/mp/login`（`WECHAT_APPID`/`WECHAT_SECRET` 已配置；Secret 缺失时降级为 `dev_<code>` 测试 openid）。
5. ✅ 领任务 `GET /api/mp/tasks`、词条列表 `GET /api/mp/tasks/{id}/words`、进度 `GET /api/mp/recordings/progress`、省列表 `GET /api/mp/regions`。
6. ✅ 后台录音审核页 + §7 三个接口（`GET /api/review/recordings`、`POST .../verdict`、`PATCH .../transcript`），管理员试听后通过/驳回，并可为录音填写普通话/方言转写，状态流转打通。
7. ✅ 数据集导出 `GET /api/review/export`（approved 录音批量导出：ZIP 音频 + `manifest.csv`，省管理员本省隔离；manifest 含发音人性别/年龄段中文列与**转写文本列**）。
8. ✅ 发音人画像采集：登录 + 上传附带 `gender`/`age_bracket`（空不覆盖）+ `POST /api/mp/profile` 自助修改（空串清空）。`POST /api/mp/profile` 同时支持 `nickname`/`avatar_url` 更新（「我的」页头像昵称编辑）。
8b. ✅ **我的录音时长导出**：「我的 → 导出录音时长」`GET /api/mp/me/durations`（统计预览）+ `GET /api/mp/me/export`（CSV 明细）→ `wx.downloadFile` 下载 → `wx.saveFile` 存本地 → `wx.shareFileMessage` 分享到文件传输助手/好友。任务进度条以「需录 N 条」为目标（`pages/tasks`）。
9. ✅ **强制登录门禁**：小程序底部 TabBar = 首页 / 我的；登录页为入口（`pages/login/login`），`wx.login` 静默换 token → 登录后「完善资料（可选）」步骤（`open-type="chooseAvatar"` + `type="nickname"` 输入框 + **性别/年龄段选择器**，保存调 `POST /api/mp/profile` 一并落库，均可跳过）→ `switchTab` 进首页；「我的」页含头像昵称编辑、性别/年龄段画像、退出登录（`clearToken` → 回登录页）。首页仅保留录音台（审核进度 / 队列统计 / 开始录音 / 领任务 / 一键上传）。
9b. ✅ **团队绑定门禁（阶段八）**：未绑定发音人在登录完成步骤**必填团队码**（`POST /api/mp/team/join` 一并绑定）；已绑定直接进首页。首页顶部「未加入团队」提示条 + 绑定弹窗；任务/画像/我的页属地**只读**展示「省·市」（`utils/region.js`）。服务端强制：任务列表 / 词条 / 上传均按属地省+市过滤（未绑定=空列表、不能上传；跨区 403）。
9c. ✅ **协议三勾选 + 强制确认（阶段九）**：登录页三行 checkbox（用户协议 / 隐私政策 / 声音单独授权协议）**全勾才能点登录**；登录后 `pending_agreements` 非空弹确认窗，「同意并继续」调 `POST /api/mp/agreements/accept`；协议详情页 `pages/agreement`（scroll-view 滚动全文）。后台改协议升版本 → 发音人下次登录只弹被改的那份（冷启动走 `GET /api/mp/agreements/pending`）。后端 403 强制拦截不可绕过。
10. 联调闭环：开发者工具/真机打开 → 登录页微信登录（**先三勾选协议**）→ 协议确认弹窗同意 → 完善头像昵称（可跳过）→ 首页领任务 → 逐条录音 → 一键提交 → 后台 `speakers`/`recordings` 表出现数据（含头像昵称/画像）→ 后台审核（通过/驳回）→ 首页进度更新 → `/media` 可试听 → 审核通过后导出数据集（manifest 含画像列）。

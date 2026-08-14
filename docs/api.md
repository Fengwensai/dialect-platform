# 管理后台 API 接口文档

方言采集平台管理后台后端。技术栈：FastAPI + SQLAlchemy 2，运行时自带的交互式文档：`http://127.0.0.1:8000/docs`。

- **Base URL**：开发环境 `http://127.0.0.1:8000`，所有接口前缀 `/api`
- **数据格式**：请求/响应均为 JSON（Excel 上传除外）
- **认证**：除 `/api/health`、`/api/auth/login` 外，全部接口需要 `Authorization: Bearer <token>`

---

## 目录

1. [认证与通用约定](#1-认证与通用约定)
2. [auth — 认证](#2-auth--认证)
3. [excel — Excel 解析入库](#3-excel--excel-解析入库)
4. [words — 词条库](#4-words--词条库)
5. [regions — 行政区划](#5-regions--行政区划)
6. [tasks — 任务包](#6-tasks--任务包)
7. [users — 管理员管理](#7-users--管理员管理)
8. [speakers — 发音人管理](#8-speakers--发音人管理)
9. [team-codes — 团队码管理](#9-team-codes--团队码管理)
10. [health — 健康检查](#10-health--健康检查)
11. [agreements — 协议管理](#11-agreements--协议管理)
12. [权限与错误码速查](#12-权限与错误码速查)
13. [典型调用流程](#13-典型调用流程)

---

## 1. 认证与通用约定

### 1.1 获取 Token

调用 `POST /api/auth/login` 获取 JWT，之后所有请求头携带：

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### 1.2 Token 载荷

JWT（HS256）内包含：

```json
{
  "admin_id": 1,
  "role": "super_admin",
  "province_code": "",
  "username": "admin",
  "exp": 1780000000
}
```

`province_code` 省管理员为所辖省 adcode（如 `13`），超管为空字符串。过期时间由 `.env` 的 `JWT_EXPIRE_MINUTES` 控制。

### 1.3 鉴权失败（HTTPBearer 统一处理）

| 状态码 | detail | 场景 |
|---|---|---|
| 401 | `未登录` | 未携带 `Authorization` 头 |
| 401 | `登录已过期，请重新登录` | Token 缺失/伪造/过期（`PyJWTError`） |
| 401 | `账号不存在` | Token 合法但用户已被删除 |
| 403 | `需要超级管理员权限` | 调用超管专属接口（`/api/users/*`） |

### 1.4 权限模型

| 角色 | 可访问 | 受限点 |
|---|---|---|
| `super_admin`（超管） | 全部接口 | 无 |
| `province_admin`（省管理员） | 除 `/api/users/*` 外全部 | 词条/任务仅限 `province_code` 管辖范围；导入仅限本省区划 |

省管理员的所有越权操作返回 `403`。

---

## 2. auth — 认证

### 2.1 登录

`POST /api/auth/login`

**请求体**：

```json
{ "username": "admin", "password": "admin123" }
```

**响应 200**：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "admin": {
    "id": 1,
    "username": "admin",
    "name": "超级管理员",
    "role": "super_admin",
    "province_code": null,
    "created_at": "2026-08-01T10:00:00Z"
  }
}
```

**错误**：`401 {"detail": "用户名或密码错误"}`

### 2.2 当前用户

`GET /api/auth/me`

**响应 200**：`AdminOut`（同上 `admin` 对象，含 `created_at`）。

---

## 3. excel — Excel 解析入库

流程：**上传预览 → 前端确认映射 → 确认导入**。解析规则见 `excel_parser.py`：

- 默认列头：`编号 / 方言点 / 词条内容 / 例句 / 备注`（可选 `发音提示`），通过别名自动识别映射。
- 只有「词条内容」非空的行才算有效行。
- 区划自动匹配：解析「方言点」文本 → 回填省/市/区 adcode；文件名含省名（如"河北省词表.xlsx"）时作为默认省兜底。

### 3.1 上传解析预览

`POST /api/excel/upload`（multipart/form-data，字段 `file`）

**请求**：`file=@河北省词表.xlsx`（仅 `.xlsx` / `.xlsm`）

**响应 200**（`UploadPreview`）：

```json
{
  "filename": "河北省词表.xlsx",
  "sheet_name": "河北省词表",
  "headers": ["编号", "方言点", "词条内容", "例句", "备注", "发音提示"],
  "mapping": { "0": "code", "1": "dialect_point", "2": "content", "3": "example_sentence", "4": "remark", "5": "pronunciation_hint" },
  "total_rows": 35,
  "rows": [
    {
      "row_index": 2,
      "code": "HB-001",
      "dialect_point": "石家庄市长安区",
      "content": "咋整",
      "example_sentence": "这事咋整啊？",
      "remark": "核心词",
      "pronunciation_hint": "zǎ zhěng",
      "region_matched": true
    }
  ],
  "raw_rows": [["HB-001", "石家庄市长安区", "咋整", "这事咋整啊？", "核心词", "zǎ zhěng"]]
}
```

**字段说明**：

| 字段 | 含义 |
|---|---|
| `mapping` | `表头列索引(字符串) → 目标字段` 的自动映射，前端可改后回传 |
| `rows` | 已整理的有效行（`content` 非空），`region_matched` = 是否解析出市/区县（`bool(city_code or district_code)`），仅文件名兜底到省的行会被标记 `false` |
| `raw_rows` | 每行原始单元格字符串，与 `rows` 位置一一对应，供前端改映射后重建行数据 |

**错误**：`400 {"detail": "仅支持 .xlsx/.xlsm 格式"}`、`400 {"detail": "文件内容为空"}`

### 3.2 确认导入

`POST /api/excel/import`

**请求体**（`ImportRequest`）：

```json
{
  "filename": "河北省词表.xlsx",
  "mapping": { "0": "code", "1": "dialect_point", "2": "content", "3": "example_sentence", "4": "remark", "5": "pronunciation_hint" },
  "rows": [ { "row_index": 2, "code": "HB-001", "dialect_point": "石家庄市长安区", "content": "咋整", "example_sentence": "…", "remark": "…", "pronunciation_hint": "…", "region_matched": true } ]
}
```

**响应 200**（`ImportResult`）：

```json
{
  "success_count": 35,
  "fail_count": 0,
  "errors": []
}
```

**行为要点**：

- 逐行入库，区划再次匹配并回填；入库时对字段截断到列长（`code` 64 / `content` 255 / 其余 500）。
- `region_matched` 为 `false` 的行仍会入库（区划仅文件省份兜底或为空），便于前端标记"待确认"。
- **省管理员限制**：匹配后区划不属于本省的行**不拒绝整个请求**，而是计入 `errors`，`fail_count` 递增。
- 空 `content` 行直接跳过（不计成功/失败）。
- 每次导入写一条 `excel_import_logs` 审计记录。

**错误**：

```json
{
  "success_count": 34,
  "fail_count": 1,
  "errors": [ { "row": 63, "content": "溜达", "reason": "区划不属于本管理员管辖范围或无法匹配" } ]
}
```

---

## 4. words — 词条库

### 4.1 词条列表（分页 + 筛选）

`GET /api/words`

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `province_code` | string | 否 | 省 adcode |
| `city_code` | string | 否 | 市 adcode |
| `district_code` | string | 否 | 区县 adcode |
| `keyword` | string | 否 | 模糊匹配 `词条内容 / 方言点 / 编号`（`LIKE %kw%`） |
| `status` | string | 否 | `active` 启用 / `disabled` 禁用；不传 = 全部（非法值 422） |
| `page` | int ≥1 | 否 | 页码，默认 1 |
| `page_size` | int 1–200 | 否 | 每页条数，默认 20 |

**响应 200**：按 `id` 倒序。

```json
{
  "total": 35,
  "items": [
    {
      "id": 1,
      "code": "HB-001",
      "dialect_point": "石家庄市长安区",
      "content": "咋整",
      "example_sentence": "这事咋整啊？",
      "remark": "核心词",
      "pronunciation_hint": "zǎ zhěng",
      "province_code": "13",
      "city_code": "1301",
      "district_code": "130102",
      "status": "active",
      "created_at": "2026-08-01T10:00:00Z"
    }
  ]
}
```

**省管理员**：范围自动钳制为本省 —— 即使显式传 `province_code=11`，也只会查 `13` 的数据（不会返回空，也不会越权）。

> **状态语义**：`status` 默认 `active`（启用）；`disabled`（禁用）表示该词条**暂时下架**——小程序端已发布任务里不再展示/不可采录，已采集录音保留。任务创建/编辑选词条时传 `status=active` 只列启用词条。

### 4.2 修改词条

`PATCH /api/words/{word_id}`

**请求体**（`WordUpdate`，全部可选，`exclude_unset` 语义）：

```json
{ "content": "咋整啊", "remark": "改后备注" }
```

**特殊逻辑**：

- 只改 `dialect_point` 且**未显式传区划字段**时，自动按新方言点重新匹配省市区；匹配不到的部分沿用旧值。
- 显式传了 `province_code / city_code / district_code` 中任意一个，则以显式值为准，不触发重匹配。
- `status` 传 `"active"` 启用 / `"disabled"` 禁用（开关切换）；非法值或 `null` → 422。

**响应 200**：更新后的 `WordOut`。

**错误**：`404 {"detail": "词条不存在"}`、`403 {"detail": "无权操作其他省份词条"}`、`422 {"detail": "status 仅支持 active/disabled"}`

### 4.3 删除词条

`DELETE /api/words/{word_id}`

**响应 200**：`{"ok": true}`

**行为**：级联删除 `task_batch_items` 中的引用，避免孤儿数据。

**错误**：`404 {"detail": "词条不存在"}`、`403 {"detail": "无权操作其他省份词条"}`

---

## 5. regions — 行政区划

### 5.1 区划三级树

`GET /api/regions/tree`

**响应 200**：省 → 市 → 区县 三层，按 `code` 升序，直接适配 Element Plus Cascader。

```json
[
  {
    "code": "13",
    "name": "河北省",
    "children": [
      {
        "code": "1301",
        "name": "石家庄市",
        "children": [
          { "code": "130102", "name": "长安区", "children": [] },
          { "code": "130104", "name": "桥西区", "children": [] }
        ]
      }
    ]
  }
]
```

> 若区划数量大，后续可改为懒加载（按父 code 分批返回），当前一次性返回全部（3429 条）足够。

---

## 6. tasks — 任务包

### 6.1 创建任务包

`POST /api/tasks`

**请求体**（`TaskBatchCreate`）：

```json
{
  "name": "河北省核心词任务",
  "description": "第一批发音任务",
  "province_code": "13",
  "city_code": null,
  "district_code": null,
  "team_code": "HB-SJZ",
  "required_audio_count": 30,
  "claim_limit": 10,
  "word_ids": [1, 2, 3, 4, 5, 6]
}
```

**字段**：`name` 必填；`province_code` 必填；`city_code`/`district_code` 为空 = 全省/全市投放；`team_code` 可选（阶段八·任务关联团队）；`required_audio_count` 默认 30；`claim_limit` 默认 10（阶段十一·每人领取上限）；`word_ids` 允许为空（后续再补词条）。

> **`team_code` 关联语义（阶段八）**：传入团队码时，团队须存在（否则 422「团队码不存在」）；**投放区划由团队码自动带出**——`province_code`/`city_code` 必须与团队属地一致，否则 422「任务地区与团队码地区不一致，选择团队后地区由团队码自动带出」；`district_code` 被清空（团队码仅精确到市）。省管理员只能关联本省团队码（403「只能关联本省的团队码」）。`team_code` 仅作归属追溯/筛选，**小程序端隔离仍按省+市**（见 `docs/miniprogram-api.md`）。

**响应 200**（`TaskBatchOut`，初始 `status="draft"`）：

```json
{
  "id": 1,
  "name": "河北省核心词任务",
  "description": "第一批发音任务",
  "province_code": "13",
  "city_code": "1301",
  "district_code": null,
  "team_code": "HB-SJZ",
  "required_audio_count": 30,
  "claim_limit": 10,
  "status": "draft",
  "created_by": 1,
  "created_at": "2026-08-07T09:00:00Z",
  "published_at": null,
  "word_count": 6
}
```

**错误**：
- `403 {"detail": "只能给自己管辖省份创建任务"}`（省管理员手选非本省省份）
- `422 {"detail": "团队码不存在"}`（关联的团队码未建）
- `403 {"detail": "只能关联本省的团队码"}`（省管理员关联他省团队）
- `422 {"detail": "任务地区与团队码地区不一致，选择团队后地区由团队码自动带出"}`

### 6.2 任务列表

`GET /api/tasks`

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string | 否 | `draft` / `published` / `closed` |
| `team_code` | string | 否 | 按关联团队码筛选（自动转大写） |
| `page` | int ≥1 | 否 | 默认 1 |
| `page_size` | int 1–200 | 否 | 默认 20 |

**响应 200**：按 `id` 倒序，`word_count` 为真实词条数（一次分组计数，无 N+1 查询）。

```json
{ "total": 1, "items": [ /* TaskBatchOut 数组，同 6.1 */ ] }
```

**省管理员**：仅返回 `province_code == 本省` 的任务。

### 6.3 发布任务

`POST /api/tasks/{batch_id}/publish`

**响应 200**：`status` 变为 `"published"`，`published_at` 写入 UTC 时间，返回完整 `TaskBatchOut`。

**错误**：

- `404 {"detail": "任务不存在"}`
- `403 {"detail": "无权操作其他省份任务"}`
- `400 {"detail": "仅草稿任务可发布"}`（重复发布/已关闭任务）

### 6.4 编辑草稿任务

`PATCH /api/tasks/{batch_id}`

仅 `draft` 状态可编辑；已发布/已关闭任务返回 400。

**请求体**（`TaskBatchUpdate`，全部可选，`exclude_unset` 语义）：

```json
{
  "name": "河北省核心词任务（改）",
  "description": "任务说明",
  "required_audio_count": 50,
  "claim_limit": 20,
  "word_ids": [1, 2, 3],
  "team_code": "HB-SJZ"
}
```

- 缺省字段 = 不改；`description` 传 `null` = 清空说明。
- `word_ids` 一旦提供则**整体替换**任务词条集合（先清后插，`word_count` 同步更新）。
- 省管理员编辑时，词条被钳制为本省词条。
- `team_code`（阶段八）：改绑团队时**投放区划随团队码覆盖**（`province_code`/`city_code` 改为团队属地，`district_code` 清空）；传 `null` = **解除关联**，保留当前地区仅去掉团队码归属。校验同 6.1（团队存在 / 省管理员限本省）。

**响应 200**：更新后的 `TaskBatchOut`（同 6.1）。

**错误**：
- `404 {"detail": "任务不存在"}`
- `403 {"detail": "无权操作其他省份任务"}`
- `400 {"detail": "仅草稿任务可编辑"}`
- `422 {"detail": "团队码不存在"}` / `403 {"detail": "只能关联本省的团队码"}`（改绑团队时）

### 6.5 关闭任务

`POST /api/tasks/{batch_id}/close`

仅 `published` 状态可关闭。关闭后小程序端**不再展示该任务**（`GET /api/mp/tasks` 只返回 published），已采集录音保留。

**响应 200**：`status` 变为 `"closed"`，返回完整 `TaskBatchOut`。

**错误**：
- `404` / `403`（同 6.4）
- `400 {"detail": "仅已发布任务可关闭"}`（草稿/已关闭）

### 6.6 重新打开任务

`POST /api/tasks/{batch_id}/reopen`

仅 `closed` 状态可重新打开。打开后任务回到 `published`，小程序端**重新展示**（`GET /api/mp/tasks` 即可见），发音人可继续采录；已采集录音保留。`published_at` 刷新为当前时间。

**响应 200**：`status` 变为 `"published"`，返回完整 `TaskBatchOut`。

**错误**：
- `404` / `403`（同 6.4）
- `400 {"detail": "仅已关闭任务可重新打开"}`（草稿/已发布）

### 6.7 删除任务

`DELETE /api/tasks/{batch_id}`

任意状态（草稿/已发布/已关闭）可删除，连带清空其词条关联与领取记录；若任务已有录音则拒绝删除（保护采集成果）。

**响应 200**：`{"detail": "已删除"}`

**错误**：
- `404` / `403`（同 6.4）
- `400 {"detail": "该任务已有录音，不能删除"}`

### 6.8 查看任务词条

`GET /api/tasks/{batch_id}/words`

**响应 200**：`WordOut` 数组（按加入顺序），字段见 §4。任意状态可查。

**错误**：`404 {"detail": "任务不存在"}`、`403`（省管理员跨省）

### 6.9 任务领取记录（阶段十一·领取制）

`GET /api/tasks/{batch_id}/claims`

返回该任务**全部领取记录**（含已录/未录），供后台解绑未录词条。省管理员受属地钳制（仅本省任务）。

**响应 200**（`TaskClaimAdminOut` 数组，按 `word_id` 升序）：

```json
[
  {
    "claim_id": 11,
    "word_id": 101,
    "content": "早晨",
    "speaker_id": 3,
    "nickname": "石家庄发音人",
    "recorded": true,
    "claimed_at": "2026-08-14T10:00:00Z"
  }
]
```

**字段**：`recorded` = 该词条是否已有录音（**已录不可解绑**）；无领取时返回 `[]`。

**错误**：`404` / `403`（同 6.4）

### 6.10 解绑领取（后台）

`DELETE /api/tasks/{batch_id}/claims/{claim_id}`

把某条领取解绑，词条**回到池子**可被他人领取。仅**未录制**的领取可解绑（已录 → 400）。

**响应 200**：`{"detail": "已解绑"}`

**错误**：
- `404 {"detail": "领取记录不存在"}`
- `400 {"detail": "该词条已录制，不能解绑"}`（已录不可解绑，需先驳回/删除该录音）

---

## 7. users — 管理员管理

> 全部接口仅 `super_admin` 可调用，否则 `403 {"detail": "需要超级管理员权限"}`。

### 7.1 管理员列表

`GET /api/users`

**响应 200**：`AdminOut` 数组（不含 `password_hash`）。

```json
[
  { "id": 1, "username": "admin", "name": "超级管理员", "role": "super_admin", "province_code": null, "created_at": "…" },
  { "id": 2, "username": "hebei_admin", "name": "河北管理员", "role": "province_admin", "province_code": "13", "created_at": "…" }
]
```

### 7.2 创建管理员

`POST /api/users`

**请求体**（`UserCreate`）：

```json
{ "username": "henan_admin", "password": "admin123", "name": "河南管理员", "role": "province_admin", "province_code": "41" }
```

**校验**：`password` 最短 6 位；`role` ∈ {`super_admin`, `province_admin`}，默认 `province_admin`；省管理员**必须**提供 `province_code`；`username` 全局唯一。

**响应 200**：新建的 `AdminOut`。

**错误**：`400 {"detail": "角色不合法"}`、`400 {"detail": "省管理员必须指定省份"}`、`400 {"detail": "用户名已存在"}`

### 7.3 修改管理员

`PATCH /api/users/{user_id}`

**请求体**（`UserUpdate`，全部可选）：`password`、`name`、`role`、`province_code`。传 `password` 时重新 bcrypt 哈希。

**响应 200**：更新后的 `AdminOut`。

**错误**：`404 {"detail": "管理员不存在"}`、`400 {"detail": "省管理员必须指定省份"}`

### 7.4 删除管理员

`DELETE /api/users/{user_id}`

**响应 200**：`{"ok": true}`

**错误**：`404 {"detail": "管理员不存在"}`、`400 {"detail": "不能删除自己"}`

---

## 8. speakers — 发音人管理

发音人即小程序端使用者。后台可**分页查看/筛选**发音人（含性别/年龄段画像与录音数），**编辑画像**（含**属地纠错**：省+市），并**行内查看单个发音人的录音明细**（列表 + 审核状态分布 + 贡献统计）。

- **属地（省+市）是阶段八隔离的核心**：由小程序端团队码绑定写入（见 `docs/miniprogram-api.md`），后台只读展示；发音人的任务可见性/录音权限严格按省+市隔离。
- **团队码**：发音人绑定团队码后锁定属地；后台纠错改属地会自动**清空 `team_code`**（原绑定作废，可重新绑定）。
- 超管看全国、可改任意省；省管理员**仅见/可改本省发音人**（`province_code == 本省`），且可给本省「未绑定」发音人补属省市。

### 8.1 发音人列表（分页 + 筛选）

`GET /api/speakers`

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `keyword` | string | 否 | 模糊匹配 `昵称 / device_id / openid`（`LIKE %kw%`） |
| `province_code` | string | 否 | 省 adcode |
| `gender` | string | 否 | `male` / `female` / `other`（非法值 422） |
| `age_bracket` | string | 否 | `under18` / `age18_30` / `age31_45` / `age46_60` / `over60`（非法值 422） |
| `page` | int ≥1 | 否 | 页码，默认 1 |
| `page_size` | int 1–200 | 否 | 每页条数，默认 20 |

**响应 200**：按 `created_at` 倒序。

```json
{
  "total": 2,
  "items": [
    {
      "id": 5,
      "openid": "oXk...",
      "device_id": "dev_xxx",
      "nickname": "张老师",
      "province_code": "13",
      "city_code": "1301",
      "team_code": "HB-SJZ",
      "gender": "female",
      "age_bracket": "age31_45",
      "recording_count": 12,
      "created_at": "2026-08-07T09:00:00Z"
    }
  ]
}
```

- `city_code`：市级 adcode（团队码绑定的市，如 `1301`）。
- `team_code`：该发音人绑定的团队码；`province_code`/`city_code` 有值但 `team_code` 为 `null` 表示属地为后台纠错/补录，非团队码绑定。

**省管理员**：范围自动钳制为本省发音人（`province_code == 本省`），超管不限制。

**错误**：`422 {"detail": "gender 仅支持 male/female/other"}` 等（非法筛选值）。

### 8.2 编辑发音人画像

`PATCH /api/speakers/{speaker_id}`

**请求体**（全部可选，`exclude_unset` 语义）：

```json
{
  "gender": "female",
  "age_bracket": "age18_30",
  "province_code": "13",
  "city_code": "1310"
}
```

- 缺省字段 = 不改；`null` / 空串 `""` = **清空**该字段；非法值 422。
- 昵称、device_id、openid 等不可改；前端弹窗可改性别/年龄段 + 属地（省+市）。
- **属地纠错**：`province_code` 须为一级省级码，`city_code` 须为归属该省的二级市级码（`422` 否则）；省管理员不能把属地改到本省之外（`403`），但可给本省「未绑定」发音人补省+市。
- **改属地后 `team_code` 自动清空**（原团队绑定作废，发音人可凭新团队码重新绑定；前端确认框会提示）。

**响应 200**：更新后的 `SpeakerAdminOut`（同 8.1 列表项结构，含 `city_code`/`team_code`）。

**错误**：
- `404 {"detail": "发音人不存在"}`
- `403 {"detail": "只能操作本省发音人"}`（省管理员跨省编辑）
- `403 {"detail": "省管理员不能把属地改到本省之外"}`
- `422 {"detail": "province_code 无效，须为有效省级代码"}` / `422 {"detail": "city_code 无效，须为归属该省的市级代码"}`

### 8.3 发音人录音明细（分页列表 + 贡献统计）

`GET /api/speakers/{speaker_id}/recordings`

发音人行内查看其**录音列表 / 审核状态分布 / 贡献统计**。超管可查任意发音人；省管理员仅可查本省发音人（403 越省）。

**查询参数**：`page` / `page_size`（默认 20）、`status`（`pending`/`approved`/`rejected`，可选，非法值 422）、`task_id`（可选）。

**响应 200**：

```json
{
  "speaker_id": 4,
  "total": 3,
  "items": [
    {
      "id": 10,
      "task_id": 4,
      "task_name": "河北省核心词任务",
      "word_id": 27,
      "word_code": "HB-006",
      "word_content": "麻利儿",
      "status": "approved",
      "audio_url": "/media/recordings/4/4_27_4.wav",
      "audio_duration": 2580,
      "file_size": 82604,
      "review_note": null,
      "reviewed_at": "2026-08-07T19:21:54Z",
      "created_at": "2026-08-07T19:21:19Z"
    }
  ],
  "stats": {
    "total": 3,
    "pending": 0,
    "approved": 2,
    "rejected": 1,
    "total_duration_ms": 8360,
    "approved_duration_ms": 5540,
    "rejected_duration_ms": 2820,
    "tasks": [{ "task_id": 4, "task_name": "河北省核心词任务", "count": 3 }]
  }
}
```

- `items`：该发音人的录音，按 `created_at` 倒序；`status`/`task_id` 筛选作用于 `items` 与 `total`。
- `stats`：发音人**全量贡献统计**（不受当前列表筛选影响）——`pending/approved/rejected` 按状态计数、`total_duration_ms` 总时长、`approved_duration_ms` **有效时长**（审核通过录音总时长）、`rejected_duration_ms` **无效时长**（驳回录音总时长）、`tasks` 按任务聚合（按录音数倒序）。
- `items[].audio_url` 可直接 `/media` 试听。

**错误**：
- `404 {"detail": "发音人不存在"}`
- `403 {"detail": "只能查看本省发音人"}`（省管理员跨省）
- `401` 未登录

### 8.4 导出发音人时长汇总 CSV

`GET /api/speakers/export`

把发音人**时长汇总**导出为 CSV（`utf-8-sig` BOM，Excel 双击直接打开中文不乱码）。全量导出、不受分页影响，遵循与 8.1 相同的筛选参数（`keyword` / `province_code` / `gender` / `age_bracket`，非法值 422）。

**响应 200**：`text/csv`，每行一个发音人，列如下（时长为**毫秒整数**，与系统 `audio_duration` 一致，无舍入误差）：

| 列 | 说明 |
|---|---|
| 发音人ID / 昵称 / 设备ID | 基础信息 |
| 省份 / 性别 / 年龄段 | 中文显示 |
| 录音总数 / 待审核数 / 通过数 / 驳回数 | 按状态计数 |
| 总时长_ms / 有效时长_ms / 无效时长_ms | 总时长、审核通过时长、驳回时长 |

文件名：`speakers_duration_YYYYMMDD_HHMMSS.csv`。

**错误**：`401` 未登录；非法筛选值 `422`。

### 8.5 导出发音人录音明细 CSV

`GET /api/speakers/{speaker_id}/recordings/export`

把单个发音人的录音明细导出为 CSV（`utf-8-sig`）。全量导出，遵循与 8.3 相同的 `status` / `task_id` 筛选。

**响应 200**：`text/csv`，每行一条录音，列：`录音ID / 任务 / 词条编码 / 词条内容 / 状态(中文) / 时长_ms / 文件大小_B / 审核备注 / 审核时间 / 提交时间 / 音频路径`。

文件名：`speaker_{speaker_id}_recordings_YYYYMMDD_HHMMSS.csv`。

**错误**：`404` 发音人不存在、`403` 省管理员跨省、`401` 未登录。

### 8.6 删除发音人

`DELETE /api/speakers/{speaker_id}`

**仅限无录音的发音人**（有录音则拒绝，保护采集成果）。连带清理：该发音人的领取记录（`task_claims`）、协议接受记录（`speaker_agreements`）、本地头像文件。

**权限**：超管可删任意；省管理员仅限本省发音人（未绑定属地的也可删，与编辑语义一致）。

**响应 200**：`{"detail": "已删除"}`

**错误**：
- `404 {"detail": "发音人不存在"}`
- `403 {"detail": "只能删除本省发音人"}`
- `400 {"detail": "该发音人已有 N 条录音，不能删除"}`

---

## 9. team-codes — 团队码管理

**一码一区（省+市）**：每个团队码唯一绑定一个省+市（`UNIQUE(province_code, city_code)`）。发音人输入团队码即绑定该省市属地，随后只能看到/录制该地区任务（阶段八隔离，见 `docs/miniprogram-api.md` §团队绑定）。

**权限**：超管管理全国；省管理员仅管理本省团队码（越省 `403`）。**只能改名**（改区域/改码需删除后重建，避免已绑定发音人失联）。

### 9.1 团队码列表

`GET /api/team-codes`

**查询参数**：`province_code`（可选，超管可按省筛选；省管理员忽略该参数、强制本省）。

**响应 200**：按 `id` 升序。

```json
[
  {
    "id": 1,
    "code": "HB-SJZ",
    "name": "石家庄团队",
    "province_code": "13",
    "city_code": "1301",
    "created_by": 1,
    "created_at": "2026-08-08T09:00:00Z"
  }
]
```

### 9.2 创建团队码

`POST /api/team-codes`

**请求体**：

```json
{ "code": "HB-SJZ", "name": "石家庄团队", "province_code": "13", "city_code": "1301" }
```

- `code` 必填，自动 `strip` + **转大写**存储。
- `province_code` 须为一级省级码、`city_code` 须为归属该省的二级市级码（否则 `422`）。
- 省管理员只能创建本省团队码（越省 `403`）。

**错误**：
- `400 {"detail": "团队码已存在"}`（码重复）
- `400 {"detail": "该省市已有团队码（一码一区），如需更换请删除后重建"}`
- `422 {"detail": "团队码不能为空"}` / `422 {"detail": "province_code 无效..."}` / `422 {"detail": "city_code 无效..."}`
- `403 {"detail": "省管理员只能管理本省的团队码"}`

### 9.3 改名

`PATCH /api/team-codes/{team_id}`

**请求体**：`{ "name": "石家庄团队（新）" }`（非空，`422` 否则）。**仅允许改名**。

### 9.4 删除

`DELETE /api/team-codes/{team_id}`

**响应 200**：`{"ok": true}`。

- 删除后已绑定发音人的**属地保留**（不受影响），但该码不再接受新绑定。
- 404 不存在 / 403 省管理员越省。

---

## 10. health — 健康检查

`GET /api/health`

**响应 200**：`{"status": "ok"}`。无需认证。

---

## 11. agreements — 协议管理

> 全部接口仅 `super_admin` 可调用，否则 `403 {"detail": "需要超级管理员权限"}`。省管理员无此菜单（前端 `superOnly` 隐藏）。

**版本语义（阶段九）**：三类协议（`user_agreement` 用户协议 / `privacy_policy` 隐私政策 / `voice_auth` 声音单独授权协议）存数据库，每行 = 某协议的一个**不可变版本**。编辑 = 发布新版本（`version` 自增），旧版本不可修改；发布新版本后所有发音人需**重新阅读并同意**方可继续使用小程序（后端 403 强制拦截，见 `docs/miniprogram-api.md` §协议确认）。

### 11.1 三类协议最新版本

`GET /api/agreements`

**响应 200**：每类返回 `max(version)` 的那行，共 3 条，按 `AGREEMENT_TYPES` 顺序。

```json
[
  {
    "id": 1,
    "type": "user_agreement",
    "title": "用户协议",
    "version": 1,
    "content": "《方言采集平台用户协议》…",
    "updated_by": null,
    "updated_at": "2026-08-08T09:00:00Z"
  }
]
```

### 11.2 某类协议历史版本

`GET /api/agreements/history?type=user_agreement`

**响应 200**：该 type 全部版本按 `version` DESC（新→旧）。

**错误**：`422 {"detail": "type 不合法，须为 user_agreement / privacy_policy / voice_auth"}`

### 11.3 发布协议新版本

`POST /api/agreements`

**请求体**（`AgreementCreate`）：

```json
{ "type": "user_agreement", "title": "用户协议", "content": "《方言采集平台用户协议》最新全文…" }
```

**行为**：`version = max(现有)+1`（无则 1），`updated_by = admin.id`，旧版本保持不可变。标题/正文非空校验。

**响应 200**：新建的 `AgreementOut`（含新 `version`）。

**错误**：`422 {"detail": "协议标题不能为空"}` / `422 {"detail": "协议内容不能为空"}` / `422 {"detail": "type 不合法…"}`

---

## 12. 权限与错误码速查

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 参数/业务校验失败（文件格式、状态机、用户名重复、自删等） |
| 401 | 未登录 / Token 过期或非法 / 账号不存在 |
| 403 | 越权（非超管调 users、省管理员跨省操作） |
| 404 | 资源不存在（词条/任务/管理员） |
| 409 | 版本冲突（小程序端提交旧版本协议同意，见 `docs/miniprogram-api.md`） |
| 422 | Pydantic 校验失败（字段缺失、类型错误、越界） |

**错误响应统一格式**：`{"detail": "<原因>"}`（Excel 导入失败例外，见 3.2）。

**Endpoint 权限速查**：

| 接口 | super_admin | province_admin |
|---|---|---|
| `POST /api/auth/login` `GET /api/auth/me` | ✅ | ✅ |
| `POST /api/excel/upload` `POST /api/excel/import` | ✅（全省） | ✅（限本省） |
| `GET /api/words` `PATCH/DELETE /api/words/{id}` | ✅（全省） | ✅（限本省） |
| `GET /api/regions/tree` | ✅ | ✅ |
| `POST /api/tasks` `GET /api/tasks` `POST /api/tasks/{id}/publish` | ✅（全省） | ✅（限本省） |
| `GET/POST /api/users` `PATCH/DELETE /api/users/{id}` | ✅ | ❌ 403 |
| `GET /api/speakers` `PATCH/DELETE /api/speakers/{id}` `GET /api/speakers/{id}/recordings` | ✅（全省） | ✅（限本省） |
| `GET/POST /api/team-codes` `PATCH/DELETE /api/team-codes/{id}` | ✅（全省） | ✅（限本省） |
| `GET /api/agreements` `GET /api/agreements/history` `POST /api/agreements` | ✅ | ❌ 403 |

---

## 12. 典型调用流程

**超管导入河北词表并建任务：**

```
1. POST /api/auth/login                    → access_token
2. POST /api/excel/upload  (multipart)     → 预览：mapping + rows（35 行）
3. 前端确认映射（通常用默认即可）
4. POST /api/excel/import  (回传 mapping+rows) → success_count=35, fail_count=0
5. GET  /api/words?province_code=13        → 校验入库与区划回填
6. POST /api/tasks  {name, province_code:"13", word_ids:[...], required_audio_count:30}
7. POST /api/tasks/1/publish               → status="published"
8. （小程序端后续阶段）拉取该任务下发录音

**团队码 + 属地纠错：**

```
1. POST /api/team-codes  {code:"HB-SJZ", name:"石家庄团队", province_code:"13", city_code:"1301"}
   → 一码一区；发音人凭 HB-SJZ 绑定后即锁定石家庄（13·1301）
2. POST /api/mp/team/join（小程序端）       → 发音人绑团队码，属地=省+市
3. GET  /api/team-codes                     → 团队码列表（管理端「团队管理」页）
4. PATCH /api/speakers/{id}  {city_code:"1310"}
   → 发音人属地纠错（石家庄→廊坊），team_code 自动清空，任务可见性随之变化
5. DELETE /api/team-codes/{id}              → 停用某码；已绑定发音人属地保留
```

**协议维护（超管，阶段九）：**

```
1. GET  /api/agreements                       → 3 条最新版本（协议管理页初始列表）
2. POST /api/agreements  {type:"user_agreement", title:"用户协议", content:"新全文"}
   → 生成 v2（旧 v1 不可变）；保存时前端有确认框（提示所有发音人需重新同意）
3. GET  /api/agreements/history?type=user_agreement → v2、v1 两版（历史弹窗）
4. （小程序端）发音人下次登录/冷启动 → 后端 403「请先同意…」→ 弹窗重新阅读并同意 v2
```
```

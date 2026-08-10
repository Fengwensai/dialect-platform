# 数据库设计文档

方言采集平台共 **11 张表**（管理后台 7 张 + 小程序发音人端 4 张）。技术栈：PostgreSQL 15 + SQLAlchemy 2。
所有 `*_code` 字段存行政区划 **adcode**（省份 2 位、地市 4 位、区县 6 位，部分直筒子市的镇/街道为 9 位，统一 `VARCHAR(16)`）。

> 说明：表与表之间目前是**逻辑引用**（用整型 id 关联），未声明数据库级 FOREIGN KEY，便于后续按业务扩展。生产前建议补约束或改为外键。

## 表间关系总览

```
admin_users
   │ 1 创建 N ──────────────┐
   ▼                        ▼
word_library ──N 被包含 N──> task_batch_items <──N 关联 1── task_batches
   ▲   导入来源 1：N                         ▲
excel_import_logs                           │ 1 关联 N（每词一条录音）
                                           ▼
                                        recordings ──N 关联 1── speakers
                                                    ▲
                            team_codes ──N 绑定 1───┘（团队码→省+市，发音人凭码绑定）
regions  ←──── word_library / task_batches / admin_users / speakers / team_codes 的 *_code 引用其 code

agreements（协议版本，1:N）──┐
   ▲ 发布者：admin_users     │ 每人每类记录已接受的最新版本（UNIQUE(speaker_id, type)）
speaker_agreements ──────────┘
   ▲ 被接受方：speakers（1:N，接受记录归属发音人）
```

---

## 1. admin_users — 管理员账号表

**作用**：登录认证 + 角色权限。区分全国超管与按省隔离的省管理员。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `username` | varchar(64), 唯一 | 登录用户名 |
| `password_hash` | varchar(255) | bcrypt 加密后的密码（不存明文） |
| `name` | varchar(64) | 显示姓名 |
| `role` | varchar(20) | 角色：`super_admin` 超级管理员（全国）/ `province_admin` 省管理员 |
| `province_code` | varchar(16), 可空 | 省管理员管辖的省份 adcode（如 `13`=河北）；超管为空 = 全国 |
| `created_at` | timestamptz | 创建时间 |

---

## 2. regions — 行政区划表

**作用**：全国省市区静态数据，供「方言点→区划」自动匹配、前端级联选择、任务投放区划。由 `scripts/init_db.py` 从 `data/pca-code.json` 灌入（3429 条）。

| 字段 | 类型 | 含义 |
|---|---|---|
| `code` | varchar(16), PK | 行政区划 adcode |
| `name` | varchar(64) | 区划名称（如 `河北省`、`石家庄市`、`长安区`） |
| `level` | int | 层级：`1` 省 / `2` 市 / `3` 区县 |
| `parent_code` | varchar(16), 可空, 索引 | 父级区划 code（省为空） |

---

## 3. word_library — 词条库表

**作用**：核心数据表。Excel 解析入库后的方言词条，带省市区标签，是任务打包和录音的数据来源。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `code` | varchar(64) | 词条编号（Excel「编号」列，如 `HB-001`） |
| `dialect_point` | varchar(128) | 方言点文本（Excel「方言点」列，如 `石家庄市长安区`） |
| `content` | varchar(255) | 词条内容（要发音人朗读的词/句） |
| `example_sentence` | varchar(500), 可空 | 例句 |
| `remark` | varchar(500), 可空 | 备注 |
| `pronunciation_hint` | varchar(500), 可空 | 发音提示（同音字/拼音，帮助发音人正确读生僻字） |
| `province_code` | varchar(16), 可空, 索引 | 省份 adcode |
| `city_code` | varchar(16), 可空, 索引 | 地市 adcode |
| `district_code` | varchar(16), 可空, 索引 | 区县 adcode |
| `status` | varchar(20), 索引 | `active` 启用（默认）/ `disabled` 禁用（下架：小程序端不展示、不可采录，已录录音保留） |
| `created_by` | int, 可空 | 导入的管理员 id（关联 `admin_users.id`） |
| `created_at` | timestamptz | 导入时间 |

---

## 4. task_batches — 任务包表

**作用**：把一批词条打包成一个"任务单"（指定投放省份/城市/区县 + 必录音频数），下发到小程序端给发音人录制。状态机：草稿 → 已发布 → 已关闭。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `name` | varchar(128) | 任务名称 |
| `description` | varchar(500), 可空 | 任务说明 |
| `province_code` | varchar(16) | 投放省份 adcode（必填） |
| `city_code` | varchar(16), 可空 | 投放地市 adcode（空 = 全省各市） |
| `district_code` | varchar(16), 可空 | 投放区县 adcode（空 = 全市各区县） |
| `team_code` | varchar(32), 索引, 可空 | **关联的团队码**（阶段八，对应 `team_codes.code`）。创建/改绑时**投放区划由团队码带出**（省+市随团队属地覆盖，district 清空）；仅归属追溯/筛选，**小程序端隔离仍按省+市** |
| `required_audio_count` | int | 必录音频数（每个发音人需录的条数，如 30） |
| `status` | varchar(20) | 状态：`draft` 草稿 / `published` 已发布 / `closed` 已关闭 |
| `created_by` | int, 可空 | 创建的管理员 id |
| `created_at` | timestamptz | 创建时间 |
| `published_at` | timestamptz, 可空 | 发布时间 |

---

## 5. task_batch_items — 任务包词条关联表（多对多中间表）

**作用**：任务包 ↔ 词条的 N:N 关系。一个任务包含多条词条，一条词条可被多个任务包使用。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `task_batch_id` | int, 索引 | 任务包 id（关联 `task_batches.id`） |
| `word_id` | int, 索引 | 词条 id（关联 `word_library.id`） |

> 后续阶段录音上传后，可在本表追加 `record_status`、`audio_url` 等字段，实现"每词一条录音"的进度跟踪。

---

## 6. excel_import_logs — Excel 导入日志表

**作用**：审计每次 Excel 导入的结果，便于回溯"哪些行成功、哪些行被拒、为什么"。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `filename` | varchar(255) | 导入的文件名 |
| `total_rows` | int | 文件有效行数（词条内容非空） |
| `success_count` | int | 成功入库条数 |
| `fail_count` | int | 失败条数 |
| `errors` | json | 失败明细数组：`[{row, content, reason}]` |
| `admin_id` | int, 可空 | 执行导入的管理员 id |
| `imported_at` | timestamptz | 导入时间 |

---

## 7. speakers — 发音人表（小程序端）

**作用**：小程序发音人身份。本期过渡方案用 `device_id`（小程序本地生成的稳定 ID）识别，不接微信登录；`openid` 字段预留，接入 `wx.login` 后作为正式身份标识并回填。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `device_id` | varchar(64), 唯一, 索引, 可空 | 本期身份标识：小程序本地持久化的设备 ID，首次上传自动建档 |
| `openid` | varchar(64), 唯一, 索引, 可空 | 微信 openid（预留，`wx.login` 就绪后写入） |
| `nickname` | varchar(64) | 昵称；未提供时后端默认 `发音人+device_id 末4位` |
| `avatar_url` | varchar(255), 可空 | 头像 |
| `province_code` | varchar(16), 索引, 可空 | **属地省份 adcode（阶段八：唯一来源是团队码绑定）**。绑定后锁定，后台纠错才可改 |
| `city_code` | varchar(16), 索引, 可空 | **属地地市 adcode**，与 `province_code` 构成省+市隔离粒度 |
| `team_code` | varchar(32), 索引, 可空 | **绑定的团队码**（对应 `team_codes.code`）。后台纠错改属地后自动清空，发音人可重新绑定 |
| `gender` | varchar(10), 可空 | 发音人画像：`male/female/other`。登录/上传附带（空不覆盖）；`POST /api/mp/profile` 可自助修改 |
| `age_bracket` | varchar(20), 可空 | 年龄段画像：`under18/age18_30/age31_45/age46_60/over60`。采集规则同 gender |
| `created_at` | timestamptz | 建档时间 |

> 阶段八属地隔离：`province_code`/`city_code` 有值但 `team_code` 为空 = 属地为后台纠错/补录（非团队码绑定）；三者皆空 = 未绑定团队，小程序端**只能看空任务、不能上传**（`400 请先加入团队`）。
>
> 数据集导出 `manifest.csv` 中 `speaker_gender`/`speaker_age_bracket` 两列将画像码显示为中文（男/女/其他、<18/18-30/31-45/46-60/>60）。

## 8. recordings — 录音表（小程序端）

**作用**：发音人上传的每条录音。`task_id + word_id` 定位任务中的词条，`speaker_id` 关联发音人；同一 `(task_id, word_id, speaker_id)` 重复上传走**覆盖**策略（重录），`recording_id` 保持稳定。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `task_id` | int, 索引 | 所属任务（关联 `task_batches.id`） |
| `word_id` | int, 索引 | 对应词条（关联 `word_library.id`） |
| `speaker_id` | int, 索引 | 发音人（关联 `speakers.id`） |
| `audio_url` | varchar(255) | 音频相对路径（如 `/media/recordings/4/4_22_1.wav`，前缀 `/media` 静态服务） |
| `audio_duration` | int | 录音时长（毫秒，小程序上报） |
| `file_size` | int | 文件大小（字节，后端写入时统计） |
| `status` | varchar(20), 索引 | `pending`（待审核）/ `approved`（通过）/ `rejected`（驳回需重录） |
| `review_note` | varchar(500), 可空 | 审核意见（阶段三审核页写入） |
| `reviewed_by` | int, 可空 | 审核管理员 id |
| `created_at` | timestamptz | 上传时间 |
| `reviewed_at` | timestamptz, 可空 | 审核时间 |

> 文件存储：`backend/media/recordings/{task_id}/{task_id}_{word_id}_{speaker_id}{ext}`（可经 `MEDIA_ROOT` 环境变量覆盖根目录）；生产可换对象存储并在 `audio_url` 存完整 CDN 地址。

---

## 9. team_codes — 团队码表（阶段八）

**作用**：**一码一区（省+市）**。每个团队码唯一绑定一个省市；发音人在小程序端输入团队码即绑定该省市属地（`POST /api/mp/team/join`），随后只能看到/录制该地区任务，实现严格的省+市隔离。管理后台「团队管理」页维护。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `code` | varchar(32), 唯一, 索引 | 团队码（存储统一**大写**，如 `HB-SJZ`） |
| `name` | varchar(128) | 团队名（如 `石家庄团队`；可后台改名） |
| `province_code` | varchar(16), 索引 | 绑定省份 adcode |
| `city_code` | varchar(16), 索引 | 绑定地市 adcode |
| `created_by` | int, 可空 | 创建的管理员 id |
| `created_at` | timestamptz | 创建时间 |

**约束**：
- `UNIQUE(code)`：团队码不可重复。
- `UNIQUE(province_code, city_code)`：**一码一区**——同一省市只能有一个团队码，防止一个地区出现多个码导致隔离混乱。

**操作规则**：
- 只能**改名**；改区域/改码需删除后重建（避免已绑定发音人「失联」——属地与码解绑）。
- 删除团队码后，已绑定发音人**属地保留**（不受影响），但该码不再接受新绑定。
- 省管理员仅能管理本省团队码（越省 `403`）。
- **任务关联**：创建/编辑任务可关联团队码（`task_batches.team_code`），投放区划随团队属地自动带出；删除团队码后已关联任务的 `team_code` 保留为历史字符串（不级联删除）。

---

## 10. agreements — 协议版本表（阶段九）

**作用**：三类合规协议（用户协议 / 隐私政策 / 声音单独授权协议）的版本仓库。**每行 = 某协议的一个不可变版本**——后台「协议管理」页编辑即发布新版本（`version` 递增），旧版本不可修改；发布新版本后所有发音人需重新阅读并同意（后端 403 强制拦截，见 `docs/miniprogram-api.md` §协议确认）。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `type` | varchar(32), 索引 | 稳定类型串：`user_agreement` / `privacy_policy` / `voice_auth`（`AGREEMENT_TYPES`） |
| `title` | varchar(128) | 协议标题（如 `用户协议`） |
| `version` | int | 版本号（1 起，该 type 内自增） |
| `content` | text | 协议全文 |
| `updated_by` | int, 可空 | 发布的管理员 id（种子 v1 为空） |
| `updated_at` | timestamptz | 发布时间 |

**约束**：`UNIQUE(type, version)`（`uq_agreements_type_version`）——同类型下版本号唯一，保证不可变版本语义。

---

## 11. speaker_agreements — 发音人接受记录表（阶段九）

**作用**：记录每位发音人对每类协议**已接受的最新版本**，用于判定"待确认"（`pending_agreement_types`：按 type 取 `max(version)` 对比已接受版本，落后则待确认）。

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int, PK | 主键 |
| `speaker_id` | int, 索引 | 发音人 id（关联 `speakers.id`） |
| `type` | varchar(32) | 协议类型（同 `agreements.type`） |
| `version` | int | 已接受的版本号 |
| `accepted_at` | timestamptz | 接受时间 |

**约束**：`UNIQUE(speaker_id, type)`（`uq_speaker_agreements_speaker_type`）——每人每类仅保留一条接受记录。提交同意采用**先删后插**（幂等）：重复同意是 no-op，同意更高版本则覆盖旧记录。

---

## 备注

- 表中 `province_code`/`city_code`/`district_code` 若为空，表示该词条区划未匹配（或仅文件名省份兜底），前端显示"待确认"，可人工补全。
- `errors` 字段用 PostgreSQL 的 JSON 类型，无需单独建错误表。
- `recordings.status` 审核流转（`pending → approved / rejected`）与发音人端"已通过/需重录"展示属阶段三（审核页），本期统一存 `pending`。

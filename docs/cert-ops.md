# 方言采集平台 · HTTPS 证书运维

线上 HTTPS 用的是 **Let's Encrypt**（自动签发 + 自动续期），**不是阿里云证书**。
本页说明证书在哪、为什么你"没配过它"、怎么自动续期、以及出问题怎么查。
部署基础见 `docs/deploy-guide.md`，健康监控见 `docs/health-monitoring.md`。

---

## 1. 证书现状

| 证书名 | 覆盖域名 | nginx 引用位置 | 到期日（UTC） |
|---|---|---|---|
| `api.qlzby.com` | `api.qlzby.com`、`admin.qlzby.com` | `dialect-api.conf`、`dialect-admin.conf` | **2026-11-12** |
| `www.qlzby.com` | `qlzby.com`、`www.qlzby.com` | `dialect-www.conf` | **2026-11-13** |

> 有效期 90 天，**到期前 30 天自动续期**（即约 2026-10-13 / 10-14 各续一次）。

**关键认知：Let's Encrypt 没有控制台、没有账号、没有短信。**

它不是一个"产品"，也不存在需要你登录的网站——它是一个开放的证书颁发服务（ACME 协议），
`certbot` 是跑在服务器上的命令行客户端，首次运行时**自动**生成账户密钥（`/etc/letsencrypt/accounts/`），
直接与 LE 的 API 通信签发。

所以：**想知道证书状态，只能上服务器查，没有别的地方可看。**

```bash
# 最准的一条：看线上实际在用的证书（权威）
for d in api.qlzby.com admin.qlzby.com qlzby.com www.qlzby.com; do
  echo "=== $d ==="
  openssl s_client -connect $d:443 -servername $d </dev/null 2>/dev/null \
    | openssl x509 -noout -subject -issuer -dates
done

# certbot 视角（管理了哪几张、剩余天数）
sudo certbot certificates
```

---

## 2. 证书是怎么来的（避免误解）

**由 `deploy-bundle/deploy.sh` 在部署时自动申请**，不是手动申请的：

```bash
# deploy.sh 第 163-166 行
log "申请 Let's Encrypt 证书（首次约 30 秒；需要 80 端口可访问且域名已解析）"
certbot certonly --webroot -w /var/www/certbot \
  -d "$API_DOMAIN" -d "$ADMIN_DOMAIN" \
  --non-interactive --agree-tos -m "admin@$DOMAIN"
```

同一个脚本还负责 `apt-get install certbot`、创建 `/var/www/certbot`、写 80 端口的
ACME 校验配置（`dialect-http.conf`）。**一条 `sudo bash deploy.sh` 全部完成**——
`--non-interactive --agree-tos` 意味着中途不会有任何需要人确认的步骤。

> 首次部署于 **2026-08-14**（`api` 证书当日签发，`www` 证书次日）。这就是为什么"从没配置过 Let's Encrypt"
> 却一直在用——它被封装在部署脚本里，且 LE 本身就没有注册流程。

### ⚠️ 阿里云控制台里那两张证书是「死的」

控制台「数字证书管理服务」里有两张 `qlzby.com` 的证书，且阿里云会发到期短信：

| 证书 ID | 域名 | 状态 |
|---|---|---|
| `cert-jfqdmw` | `api.qlzby.com` / `www.api.qlzby.com` | 未部署（`已部署` 列为 `--`） |
| `cert-7phdkc` | `qlzby.com` / `www.qlzby.com` | 未部署（`已部署` 列为 `--`） |

**两张都没有被 nginx 引用**（`grep -rn ssl_certificate /etc/nginx/` 零命中），
没有在服务任何流量。**阿里云的到期短信可以忽略，不要续费、不要操作。**

> 别被"有控制台 + 有短信"误导——那个方向是死的，真正在跑的那张反而没有任何界面。

---

## 3. 自动续期链路

```
certbot.timer（systemd，每天两次）
      └─> certbot renew（到期前 30 天才真正续）
            └─> 续期成功后执行 deploy hook
                  └─> systemctl reload nginx   ← 缺了这步就是静默故障
```

**为什么最后一步必不可少**：nginx 启动时把证书读进内存，**之后替换磁盘上的文件它不会察觉**。
不 reload 的话，certbot 续期再成功，nginx 也仍在用旧证书，直到旧证书过期、全站硬失败。

```bash
systemctl status certbot.timer          # active (waiting) 且下次触发时间正常
systemctl list-timers --all | grep certbot
```

> `/etc/cron.d/certbot` 里也有一条 cron，但它有 systemd 守卫（`! -d /run/systemd/system`），
> 在 systemd 系统上不会重复执行。以 `certbot.timer` 为准。

### 为什么"免费 + 全自动"仍然需要到期提醒？

这是最容易被误解的一点：**免费说的是价格，90 天说的是有效期，两者无关。**
LE 每张证书只有 90 天寿命（CA/Browser Forum 行业规定，短有效期可限制私钥泄露的危害窗口），
到期即作废，浏览器和微信直接拒绝——**哪怕它是免费的**。

真正让"不用管"成立的是**自动化**，不是免费：

| | 含义 |
|---|---|
| 免费 | 续期不要钱 |
| 90 天有效期 | 每 90 天必须换一张新的 |
| 自动续期 | 让"换证"这件事你察觉不到 |
| **到期提醒** | 监控**自动化本身有没有失效**——不是催你交钱 |

**而自动化的失效恰恰是无声的。** §4 那个缺口就是实证：定时器在跑、续期命令成功、
磁盘上新证书就位，唯独线上实际在用的还是旧证书——只翻 certbot 日志完全看不出异常。

自动化覆盖不了的情况：服务器重装/迁移（timer 丢失）、DNS 变更或 80 端口被占
（域名验证失败）、某次排查中定时器被误禁用、磁盘满，**以及规则变更**
（CA/B 一直在缩短有效期上限，见 §1 的 90 天现状）。

### ⚠️ 现在**没有任何**自动到期提醒（2026-09-17 查实）

三个常见的"保险"全部不成立，别指望它们：

| 候选保险 | 实际情况 |
|---|---|
| Let's Encrypt 到期提醒邮件 | ❌ **已停止服务**。公告 2025-01-22，**支持终止 2025-06-04**；LE 同时**删除了所有已存储的 ACME 邮箱**（理由：自动化已普及、存百万邮箱与隐私冲突、每年数万美元成本）。这也是 `regr.json` 里 `"body": {}` 为空的原因 |
| ACME 账户邮箱 `admin@qlzby.com` | ❌ **信箱不存在**。`qlzby.com` **无任何 MX 记录**，按 RFC 退回 A 记录 → `182.92.9.204` → 该机无邮件服务 → 必然退信。该地址是 `deploy.sh` 里 `-m "admin@$DOMAIN"` 拼出来的，从未真正创建 |
| UptimeRobot 免费档 SSL 提醒 | ❌ **付费功能**（Solo $8/月起）。免费档不检查证书 |

> **UptimeRobot 免费档仍能提供 T-0 告警**：证书真过期时 TLS 握手失败 → 监控变 DOWN → 发邮件。
> 但它没有提前量——那一刻已经是全站宕机。

**当前真正在工作的自动机制只有一个：`certbot.timer` + §4 的 deploy hook。**
它一旦失灵，不会有任何东西通知你。因此**人工兜底不可省略**（见 §6）。

---

## 4. deploy hook（2026-09-17 补装）

**背景**：首次排查发现续期链路缺了 reload 这一步——
`renewal-hooks/{pre,deploy,post}` 三个目录全空、`cli.ini` 无 hook、
`certbot.service` 无 `ExecStartPost`、renewal 用 `authenticator=webroot` 无 installer
（certbot 根本不碰 nginx）。若不修，**2026-11-12 会全站硬失败，且没有任何预警**。

**修复**（已安装）：

```bash
# 文件：/etc/letsencrypt/renewal-hooks/deploy/reload-nginx
#!/bin/sh
systemctl reload nginx
```

```bash
# 重建命令（若文件丢失）
printf '#!/bin/sh\nsystemctl reload nginx\n' \
  > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
```

两个设计点：

- 用 **`deploy`** 而不是 `post`：deploy hook **只在真正续期成功后**执行，
  平时空跑不会白白 reload。
- 文件名**不带扩展名**：certbot 源码（`_internal/hooks.py:list_hooks`）用
  `os.listdir` + `is_executable` 判断、不过滤扩展名，`.sh` 也可用；
  但无扩展名额外兼容 `run-parts` 语义，两边都成立。

**验证接线**（无需真续期）：

```bash
sudo certbot renew --dry-run
grep -a "deploy hook" /var/log/letsencrypt/letsencrypt.log | tail -3
# 期望看到（每张证书一行）：
#   Dry run: skipping deploy hook command: .../renewal-hooks/deploy/reload-nginx
# "Dry run: skipping" = 演练才跳过，真实续期会执行它
```

---

## 5. 排障

| 症状 | 检查 | 处置 |
|---|---|---|
| 浏览器提示证书过期 | `sudo certbot certificates` 看剩余天数 | 立即 `sudo certbot renew --force-renewal && sudo systemctl reload nginx` |
| 续期失败 | `sudo journalctl -u certbot -n 50` | 多为 80 端口不可达 / DNS 变更；80 端口须放行 `/.well-known/acme-challenge/`（见 deploy.sh 的 `dialect-http.conf`） |
| 磁盘上证书是新的，线上仍是旧的 | 对比 `openssl` 实测的 `notAfter` 与 `certbot certificates` | **deploy hook 失效** → 见 §4 重建，然后 `systemctl reload nginx` |
| 续期成功但日志无 hook 记录 | `ls -la /etc/letsencrypt/renewal-hooks/deploy/` | 文件丢失或丢了可执行位 → 见 §4 |

> **`--dry-run` 全绿 ≠ 一切正常**：它只模拟 ACME 域名验证，**不会触发 deploy hook**。
> 演练通过不代表 nginx 会拿到新证书——必须另外确认 §4 的 hook 存在。

---

## 6. 日常检查清单

- [ ] 线上证书未过期（§1 的 `openssl` 循环，或 `sudo certbot certificates`）
- [ ] `systemctl status certbot.timer` 为 active (waiting)
- [ ] `sudo journalctl -u certbot --since "-7 days"` 无续期失败
- [ ] `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx` 存在且可执行
- [ ] **人工复查**：每 90 天一次（**没有自动提醒可用，见 §3 末**，这是唯一的提前量来源）
- [ ] 阿里云控制台的证书短信可忽略，无需处理

> 不要指望这些：LE 到期提醒邮件（2025-06 已停）、`admin@qlzby.com`
>（域名无 MX，信箱不存在）、UptimeRobot 免费档 SSL 提醒（付费功能）。
> UptimeRobot 免费档只能在**证书已过期、站点已宕**时告警，无提前量。

**下次复查节点：2026-10-13 前后**（首次真实自动续期）

```bash
sudo journalctl -u certbot --since "2026-10-12" | grep -iE "renew|hook|congrat"
# 期望：Congratulations + 我们的 reload-nginx hook 被调用
# 同时确认 openssl 实测的 notAfter 已推到 2027-01 之后
```

**再下一次：约 2026-12-12**（第二次续期）。目前没有自动提醒，
是否额外加提醒手段由自己决定——可选方案：手机日历按 90 天循环、钉钉/飞书机器人 webhook
（可复用 `dialect-monitor.timer`）、Red Sift Certificates Lite（免费）或 UptimeRobot Solo（付费）。
**不加也可以**，代价是故障只能靠"小程序打不开"这类现象被动发现。

---

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-14 | 首次部署，`deploy.sh` 自动签发 LE 证书并启用 `certbot.timer` |
| 2026-09-17 | 排查发现续期后不 reload nginx 的静默故障；补装 `reload-nginx` deploy hook 并验证接线 |
| 2026-09-17 | 查实**三个候选提醒机制全部不成立**（LE 邮件 2025-06 已停、`admin@qlzby.com` 无 MX、UptimeRobot 免费档 SSL 提醒属付费）；§3 末与 §6 据此改写，确认**当前无任何自动到期提醒** |

> 相关：`docs/deploy-guide.md` §4.5（nginx + HTTPS）、`docs/health-monitoring.md`（UptimeRobot 探活）。
> 注意 `deploy-bundle/` 被 `.gitignore` 排除，**`deploy.sh` 不在版本控制内**——
> 配置 TLS 的原始脚本只存在于本地和服务器各一份，本页是它的知识备份。

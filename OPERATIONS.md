# 运维手册

本文档记录 CEACStatusBot Web 的日常运维、备份恢复和故障排查命令。命令中的真实密钥、密码和授权码必须由运维人员在服务器上管理，不要写入仓库。

## 日常状态检查

查看服务状态：

```bash
systemctl status ceacstatusbot-backend.service --no-pager
systemctl status ceacstatusbot-worker.service --no-pager
systemctl status nginx --no-pager
```

健康检查：

```bash
curl https://ceac.mikezhuang.cn/api/health
curl http://127.0.0.1:8011/api/health
```

查看监听端口：

```bash
ss -ltnp | grep -E ':80|:443|:8011'
```

8010 不应作为公网入口；如果保留，只用于内部入口或过渡调试。

## 日志

后端日志：

```bash
tail -f /www/wwwlogs/ceacstatusbot-backend.log
tail -f /www/wwwlogs/ceacstatusbot-backend.error.log
```

Worker 日志：

```bash
tail -f /www/wwwlogs/ceacstatusbot-worker.log
tail -f /www/wwwlogs/ceacstatusbot-worker.error.log
```

Nginx 日志：

```bash
tail -f /www/wwwlogs/ceac.mikezhuang.cn.log
tail -f /www/wwwlogs/ceac.mikezhuang.cn.error.log
```

宝塔计划任务日志：

```bash
tail -f /www/server/cron/3c0e83e8c3edd66d06abb0f2d514b212.log
```

## 手动部署

执行自动同步脚本：

```bash
/www/server/cron/3c0e83e8c3edd66d06abb0f2d514b212
```

或直接执行部署脚本：

```bash
/usr/local/bin/ceacstatusbot-sync-deploy.sh
```

部署后检查：

```bash
cd /opt/ceacstatusbot
git log -1 --oneline
curl https://ceac.mikezhuang.cn/api/health
systemctl status ceacstatusbot-backend.service --no-pager
systemctl status ceacstatusbot-worker.service --no-pager
```

## SQLite 队列检查

查看任务积压：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  "select status, count(*) from query_jobs group by status;"
```

查看最近任务：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select id, case_id, trigger_type, status, attempts, created_at, finished_at, error_message from query_jobs order by id desc limit 20;"
```

如果 `queued` 或 `running` 长时间积压，先检查 Worker 服务和日志。

CEAC 立即查询和 GTS 立即查询 slot 共用每日手动查询额度：普通账号默认由 `STANDARD_DAILY_MANUAL_QUERY_LIMIT=1` 控制，Premium 默认由 `PREMIUM_DAILY_MANUAL_QUERY_LIMIT=1000` 控制，管理员账号不受限制。CEAC/GTS 业务邮件也有每日账号级限制：普通账号默认由 `STANDARD_DAILY_EMAIL_LIMIT=5` 控制，Premium 默认由 `PREMIUM_DAILY_EMAIL_LIMIT=1000` 控制，注册和重置密码验证码不计入。查看当天手动查询量：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select u.email, count(*) as manual_queries from query_jobs j join ceac_cases c on c.id = j.case_id join users u on u.id = c.user_id where j.trigger_type in ('manual', 'passport_slot_manual') and j.created_at >= datetime('now', 'start of day') group by u.id order by manual_queries desc;"
```

查看当天业务邮件发送量：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select u.email, count(*) as sent_emails from email_delivery_logs e join users u on u.id = e.user_id where e.created_at >= datetime('now', 'start of day') group by u.id order by sent_emails desc;"
```

查看最近安全事件：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select id, event_type, severity, user_id, actor_summary, path, created_at from security_events order by id desc limit 50;"
```

GTS 护照预约监控任务会使用 `passport_slot_manual` 或 `passport_slot_automatic` 触发类型：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select c.display_name, m.is_enabled, m.last_slot_count, m.next_check_at, m.last_error_message from passport_slot_monitors m join ceac_cases c on c.id = m.case_id order by m.updated_at desc limit 20;"
```

GTS 进入 `no_slot` 或 `has_slot` 后会自动停止并锁定对应 CEAC 自动查询；普通用户不能恢复，管理员可在后台恢复。发现 slot 后 GTS 轮询会放缓到约每小时一次，不再参与零点加频；用户预约成功后应在站内点击“我已预约，停止监控”。查看被 GTS 接管的档案：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select id, display_name, is_enabled, ceac_auto_locked_by_passport_slot, next_check_at from ceac_cases where ceac_auto_locked_by_passport_slot = 1 order by updated_at desc;"
```

Worker 领取队列时会按账号优先级排序，数值越小越先处理；Premium 默认 50，普通账号默认 100，管理员可手动覆盖；优先级相同则保持任务 ID FIFO：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select id, email, role, account_tier, worker_priority from users order by worker_priority asc, id asc;"
```

管理员后台的 Worker 队列区域会只读展示当前 `queued` / `running` 任务，排序与实际领取顺序一致：运行中任务优先显示，其余按 `worker_priority ASC, query_jobs.id ASC`。如果用户询问“正在排队还是正在查询”，优先看该区域的状态、等待时长和执行 Worker。

同一区域还会展示“未来预计入队”任务，这部分来自 CEAC 档案和 GTS 监控的 `next_check_at`，用于预判接下来哪些账号、档案和查询类型会进入 Worker 队列。已经存在 queued/running 任务的档案不会重复出现在未来预览中。

用户在个人信息页打开完整用户条款时，系统会写入当前条款版本、接受时间、IP 摘要和设备摘要到 `users.terms_*` 字段，并记录 `terms_accepted` 安全事件。

账号数据保留策略：如果普通账号注册约 15 天后仍未添加任何 CEAC、IRCC 或韩国签证申请档案，后台清理任务会发送空账号删除提醒并写入 `users.inactivity_notice_sent_at`；如果注册约 30 天后仍未添加任何申请档案且已经发送过提醒，会先尝试发送删除通知，再删除该用户。管理员账号不参与自动提醒或自动删除。只要账号已有任意申请档案，后台清理任务会清除已有的 `users.inactivity_notice_sent_at` 标记并永久保留该账号，不会因为没有新的状态、slot 动态或查询运行记录而自动删除。

## 备份

建议至少备份三类文件：

- SQLite 数据库：`/opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3`
- 后端环境变量：`/opt/ceacstatusbot-runtime/backend.env`
- 主密钥文件：`/opt/ceacstatusbot-runtime/secrets/credential-master.key`

示例：

```bash
BACKUP_DIR=/opt/ceacstatusbot-runtime/backups/$(date +%Y%m%d%H%M%S)
install -d -m 750 -o root -g www "$BACKUP_DIR"
cp -a /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 "$BACKUP_DIR/"
cp -a /opt/ceacstatusbot-runtime/backend.env "$BACKUP_DIR/"
cp -a /opt/ceacstatusbot-runtime/secrets/credential-master.key "$BACKUP_DIR/"
chmod -R go-rwx "$BACKUP_DIR"
```

不要只备份数据库而不备份主密钥。没有主密钥时，加密字段无法恢复。

## 恢复

恢复顺序：

1. 停止服务：

```bash
systemctl stop ceacstatusbot-worker.service
systemctl stop ceacstatusbot-backend.service
```

2. 恢复数据库、`backend.env` 和主密钥文件。
3. 恢复权限：

```bash
chown -R www:www /opt/ceacstatusbot-runtime
chmod 750 /opt/ceacstatusbot-runtime
chmod 640 /opt/ceacstatusbot-runtime/backend.env
chmod 640 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3
chown root:www /opt/ceacstatusbot-runtime/secrets/credential-master.key
chmod 0440 /opt/ceacstatusbot-runtime/secrets/credential-master.key
```

4. 启动服务：

```bash
systemctl start ceacstatusbot-backend.service
systemctl start ceacstatusbot-worker.service
```

5. 执行健康检查和一次测试查询。

## 故障排查

### 验证码邮件发不出去

检查：

```bash
tail -n 100 /www/wwwlogs/ceacstatusbot-backend.error.log
tail -n 100 /www/wwwlogs/ceacstatusbot-backend.log
```

确认管理员后台的默认发信邮箱、SMTP 主机、端口、SSL 和授权码正确。腾讯企业邮箱通常使用：

- `smtp.exmail.qq.com`
- SSL 端口 `465`

### Worker 不消费任务

检查：

```bash
systemctl status ceacstatusbot-worker.service --no-pager
tail -n 100 /www/wwwlogs/ceacstatusbot-worker.error.log
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  "select status, count(*) from query_jobs group by status;"
```

常见原因：

- Worker 服务未启动。
- SQLite 文件权限错误。
- 主密钥文件缺失或权限错误。
- CEAC 查询长时间超时。

### 密钥文件缺失导致无法解密

检查：

```bash
grep CREDENTIAL_KEY_FILE /opt/ceacstatusbot-runtime/backend.env
stat /opt/ceacstatusbot-runtime/secrets/credential-master.key
```

如果密钥文件丢失，只能从备份恢复。不要生成新密钥直接覆盖旧密钥，否则旧密文无法解密。

### Nginx 限流误伤

查看 Nginx 错误日志：

```bash
tail -n 100 /www/wwwlogs/ceac.mikezhuang.cn.error.log
```

如果确认是正常用户被误伤，可以适当提高 `burst` 或降低登录页自动重试频率。不要直接移除登录、注册和验证码接口的限流。

### CEAC 查询失败或超时

检查 Worker 日志和查询日志：

```bash
tail -n 100 /www/wwwlogs/ceacstatusbot-worker.log
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select id, success, error_message, duration_ms, finished_at from query_runs order by id desc limit 20;"
```

常见原因：

- `CEAC 首页请求失败` / `CEAC 表单提交失败`：多半是 CEAC 官网慢、网络波动或服务器出口异常。
- `CEAC 页面未返回验证码图片` / `CEAC 页面未返回办理地点下拉框`：可能是 CEAC 页面结构变化、维护或被临时拦截。
- `CEAC 验证码识别失败` / `CEAC 未返回状态结果`：常见于验证码识别失败，也可能是用户信息不匹配。
- `CEAC 提示申请号、护照号、姓氏或办理地点信息不匹配`：优先让用户核对档案信息。
- `CEAC 返回的申请号与档案申请号不一致`：应暂停该档案并核对输入，避免记录错案卷。
- 如果失败集中在同一时间段，多半是 CEAC 站点慢或服务器出口 IP 被第三方站点限制。
- 同一档案连续失败 5 次会自动发送核对信息提醒；连续失败 10 次会先降为每天一次查询；进入失败降频后 7 天内仍未恢复成功，才会自动停止 CEAC 自动查询。任意一次成功查询会清零连续失败计数和失败降频状态。

### GTS 护照预约监控无结果

检查对应任务和监控状态：

```bash
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select id, case_id, trigger_type, success, error_message, duration_ms, finished_at from query_runs where trigger_type like 'passport_slot_%' order by id desc limit 20;"
sqlite3 /opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3 \
  ".headers on" ".mode column" \
  "select case_id, is_enabled, last_slot_count, last_checked_at, next_check_at, last_error_message from passport_slot_monitors order by updated_at desc limit 20;"
```

常见原因：

- UID/HAL 尚未被 GTS 后端识别，接口返回 `token:null` 或 `invalid_uid`。
- GTS 监控会记录三态：`not_eligible` 表示暂不具备预约资格，`no_slot` 表示已可预约但暂无时间，`has_slot` 表示发现可预约时间。
- GTS 监控仍为 Beta：系统只检测 GTS 返回结果并通知，不自动预约、不占位、不抢 slot，也不保证结果完整或实时一致。
- 系统会在 `not_eligible -> no_slot`、`no_slot -> has_slot`、以及 `has_slot` 时间列表变化时发送邮件；首次 `not_eligible` 或首次 `no_slot` 只记录状态。
- 普通时段约每 1-30 分钟随机查询一次。进入 `no_slot` 后按中国时间零点加频：23:59-00:02 约 15 秒一次，23:59:45-00:00:30 核心窗口约 5 秒一次，并覆盖 00:00:00 和 00:00:02。Worker 建议保持 `WORKER_POLL_INTERVAL_SECONDS=1`。
- 零点高峰可以临时运行 2 个 Worker：常驻 `ceacstatusbot-worker.service` 加一个只在 23:58-00:04 左右启动的高峰 Worker。不要长期大幅提高并发，避免触发 CEAC/GTS 限流。
- GTS 接口限流，系统会自动把下一次查询退避到 30-60 分钟后。
- Worker 无法访问 `https://scheduling-api.gtspremium.com`。

### 自动部署没有更新

检查：

```bash
tail -n 80 /www/server/cron/3c0e83e8c3edd66d06abb0f2d514b212.log
cd /opt/ceacstatusbot && git remote -v && git log -1 --oneline
```

仓库应指向：

```text
https://github.com/Mike-Zhuang/CEACStatusBot_Web
```

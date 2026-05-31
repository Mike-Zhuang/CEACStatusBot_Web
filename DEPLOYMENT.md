# 部署说明

本文档记录 CEACStatusBot Web 的生产部署约定。不要把生产账号、密码、SMTP 授权码、主密钥或数据库写入仓库。

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `/opt/ceacstatusbot` | 代码仓库 |
| `/opt/ceacstatusbot-runtime` | 运行时数据目录 |
| `/opt/ceacstatusbot-runtime/backend.env` | 后端环境变量 |
| `/opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3` | SQLite 数据库 |
| `/opt/ceacstatusbot-runtime/secrets` | 仓库外密钥目录 |
| `/opt/ceacstatusbot-runtime/secrets/credential-master.key` | AES-256-GCM 主密钥 |
| `/var/www/ceacstatusbot/frontend/dist` | 前端构建产物 |
| `/www/wwwlogs` | Nginx、backend、worker 日志 |

运行时目录和密钥目录不受 Git 管理，自动部署脚本不得删除或覆盖。

## 仓库与自动同步

生产仓库：

```text
https://github.com/Mike-Zhuang/CEACStatusBot_Web
```

自动同步脚本：

```bash
/usr/local/bin/ceacstatusbot-sync-deploy.sh
```

计划任务通过宝塔计划任务和系统 crontab 每 10 分钟执行一次。脚本使用 git proxy 源拉取 `main`，只更新 `/opt/ceacstatusbot` 和 `/var/www/ceacstatusbot/frontend/dist`，不触碰 `/opt/ceacstatusbot-runtime`。

## 环境变量

生产 `backend.env` 至少包含：

```bash
DATABASE_PATH=/opt/ceacstatusbot-runtime/ceacstatusbot.sqlite3
SECRET_KEY=<随机强密钥>
CREDENTIAL_KEY_FILE=/opt/ceacstatusbot-runtime/secrets/credential-master.key
ENCRYPTION_KEY=<仅旧 Fernet 密文兼容需要>

SYSTEM_FROM_EMAIL=
SYSTEM_EMAIL_PASSWORD=
SYSTEM_SMTP_HOST=smtp.exmail.qq.com
SYSTEM_SMTP_PORT=465
SYSTEM_SMTP_USE_SSL=true
APP_BASE_URL=https://ceac.mikezhuang.cn

CORS_ORIGINS=https://ceac.mikezhuang.cn
CSRF_TRUSTED_ORIGINS=https://ceac.mikezhuang.cn
ALLOWED_HOSTS=ceac.mikezhuang.cn,localhost,127.0.0.1
TRUSTED_PROXY_IPS=127.0.0.1,::1
API_MAX_BODY_BYTES=131072
COOKIE_SECURE=true
SESSION_IDLE_TIMEOUT_MINUTES=720
SESSION_ABSOLUTE_TIMEOUT_DAYS=14
AUTH_LOGIN_IP_DEVICE_LIMIT_PER_MINUTE=10
AUTH_LOGIN_EMAIL_FAILURE_LIMIT_PER_15_MINUTES=5
AUTH_CODE_EMAIL_LIMIT_PER_HOUR=3
AUTH_CODE_IP_DEVICE_LIMIT_PER_10_MINUTES=3
STANDARD_API_LIMIT_PER_MINUTE=120
PREMIUM_API_LIMIT_PER_MINUTE=300
ADMIN_API_LIMIT_PER_MINUTE=600
QUERY_JOB_TIMEOUT_SECONDS=360
WORKER_POLL_INTERVAL_SECONDS=1
STANDARD_DAILY_MANUAL_QUERY_LIMIT=1
PREMIUM_DAILY_MANUAL_QUERY_LIMIT=1000
STANDARD_DAILY_EMAIL_LIMIT=5
PREMIUM_DAILY_EMAIL_LIMIT=1000
SEED_DEFAULT_USERS=false
```

`SECRET_KEY`、`ENCRYPTION_KEY`、`SYSTEM_EMAIL_PASSWORD` 不要写入 README、提交记录或聊天记录。生产建议通过管理员后台保存系统 SMTP 授权码，使其进入加密存储。

## systemd 服务

后端服务：

```ini
[Unit]
Description=CEACStatusBot FastAPI Backend
After=network.target

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/opt/ceacstatusbot
EnvironmentFile=/opt/ceacstatusbot-runtime/backend.env
Environment=UV_PYTHON_INSTALL_DIR=/opt/ceacstatusbot-python
ExecStart=/opt/ceacstatusbot/.venv/bin/python -m uvicorn CEACStatusBot.web.main:app --host 127.0.0.1 --port 8011 --proxy-headers --forwarded-allow-ips=127.0.0.1,::1
Restart=always
RestartSec=3
StandardOutput=append:/www/wwwlogs/ceacstatusbot-backend.log
StandardError=append:/www/wwwlogs/ceacstatusbot-backend.error.log

[Install]
WantedBy=multi-user.target
```

Worker 服务：

```ini
[Unit]
Description=CEACStatusBot Query Worker
After=network.target ceacstatusbot-backend.service

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/opt/ceacstatusbot
EnvironmentFile=/opt/ceacstatusbot-runtime/backend.env
Environment=UV_PYTHON_INSTALL_DIR=/opt/ceacstatusbot-python
ExecStart=/opt/ceacstatusbot/.venv/bin/python -m CEACStatusBot.web.worker
Restart=always
RestartSec=3
StandardOutput=append:/www/wwwlogs/ceacstatusbot-worker.log
StandardError=append:/www/wwwlogs/ceacstatusbot-worker.error.log

[Install]
WantedBy=multi-user.target
```

常用命令：

```bash
systemctl daemon-reload
systemctl enable --now ceacstatusbot-backend.service
systemctl enable --now ceacstatusbot-worker.service
```

## 零点高峰第二 Worker

GTS `no_slot` 零点窗口会产生秒级任务。默认常驻 1 个 Worker；如果需要在中国时间零点高峰短时提高吞吐，可以增加一个只在高峰窗口运行的第二 Worker。

高峰 Worker 服务 `/etc/systemd/system/ceacstatusbot-worker-peak.service`：

```ini
[Unit]
Description=CEACStatusBot Peak Query Worker
After=network.target ceacstatusbot-backend.service

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/opt/ceacstatusbot
EnvironmentFile=/opt/ceacstatusbot-runtime/backend.env
Environment=UV_PYTHON_INSTALL_DIR=/opt/ceacstatusbot-python
ExecStart=/opt/ceacstatusbot/.venv/bin/python -m CEACStatusBot.web.worker
Restart=no
StandardOutput=append:/www/wwwlogs/ceacstatusbot-worker-peak.log
StandardError=append:/www/wwwlogs/ceacstatusbot-worker-peak.error.log
TimeoutStopSec=20
```

启动定时器 `/etc/systemd/system/ceacstatusbot-worker-peak-start.timer`：

```ini
[Unit]
Description=Start CEACStatusBot peak worker before GTS midnight window

[Timer]
OnCalendar=*-*-* 23:58:30
Persistent=false
Unit=ceacstatusbot-worker-peak.service

[Install]
WantedBy=timers.target
```

停止服务 `/etc/systemd/system/ceacstatusbot-worker-peak-stop.service`：

```ini
[Unit]
Description=Stop CEACStatusBot peak worker after GTS midnight window

[Service]
Type=oneshot
ExecStart=/bin/systemctl stop ceacstatusbot-worker-peak.service
```

停止定时器 `/etc/systemd/system/ceacstatusbot-worker-peak-stop.timer`：

```ini
[Unit]
Description=Stop CEACStatusBot peak worker after GTS midnight window

[Timer]
OnCalendar=*-*-* 00:04:00
Persistent=false
Unit=ceacstatusbot-worker-peak-stop.service

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now ceacstatusbot-worker-peak-start.timer
systemctl enable --now ceacstatusbot-worker-peak-stop.timer
```

这样普通时段仍是 1 个 Worker，零点高峰窗口短时变成 2 个 Worker。

## Nginx 策略

生产域名：

```text
https://ceac.mikezhuang.cn
```

推荐结构：

- 域名站点直接服务 `/var/www/ceacstatusbot/frontend/dist`。
- `/api/` 反代到 `http://127.0.0.1:8011`。
- 8010 仅作为内部入口或逐步废弃入口，不作为公网入口。
- TLS 仅启用 `TLSv1.2 TLSv1.3`。
- 增加连接超时、请求限流和安全响应头。

站点级关键配置示例：

```nginx
client_max_body_size 2m;
client_header_timeout 10s;
client_body_timeout 10s;
send_timeout 15s;
keepalive_timeout 20s;

add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "same-origin" always;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;

location ^~ /api/ {
    limit_req zone=ceac_api burst=30 nodelay;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 180s;
    proxy_connect_timeout 10s;
    proxy_send_timeout 60s;
    proxy_pass http://127.0.0.1:8011;
}
```

`limit_req_zone` 需要写在 Nginx `http` 块中，不能直接写进单个 `server` 块。

## 健康检查

```bash
curl https://ceac.mikezhuang.cn/api/health
systemctl status ceacstatusbot-backend.service --no-pager
systemctl status ceacstatusbot-worker.service --no-pager
nginx -t
```

## 部署验证

部署后确认：

- Git 提交为预期的 `main` 最新提交。
- `/opt/ceacstatusbot-runtime` 未被覆盖。
- SQLite、`backend.env`、主密钥文件权限正确。
- 后端、Worker、Nginx 均正常。
- 管理员后台可加载用户资料、查询日志和系统发信配置。
- 管理员后台可编辑用户账号等级和 Worker 优先级；队列按优先级数值从小到大领取任务，同优先级按任务 ID 先进先出。Premium 默认优先级 50，普通账号默认 100。
- 立即查询会进入队列并由 Worker 完成；普通账号达到 `STANDARD_DAILY_MANUAL_QUERY_LIMIT`、Premium 达到 `PREMIUM_DAILY_MANUAL_QUERY_LIMIT` 后会收到 429 提示。
- CEAC/GTS 业务邮件同样有每日账号级限制：普通账号由 `STANDARD_DAILY_EMAIL_LIMIT` 控制，Premium 由 `PREMIUM_DAILY_EMAIL_LIMIT` 控制；注册和重置密码验证码不计入该额度。
- Approved/Issued 档案详情页可保存 UID/HAL 并创建 GTS 护照预约监控；Worker 日志中可看到 `passport_slot_manual` 或 `passport_slot_automatic` 任务。GTS 进入 `no_slot` / `has_slot` 后应自动停止并锁定 CEAC 自动查询；发现 slot 后 GTS 下次查询应约为 1 小时后。

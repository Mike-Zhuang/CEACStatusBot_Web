# CEACStatusBot Web

CEACStatusBot Web 是一个面向个人用户和小规模运营场景的自托管签证状态监控系统。它把美国签证 CEAC 查询、加拿大 IRCC Portal Alpha 监控、韩国签证状态查询、邮件通知、账号体系和管理员控制台整合到同一个可部署的 Web 应用里。

线上服务地址： [ceac.mikezhuang.cn](https://ceac.mikezhuang.cn)

[English](README.md)

> 本项目不是官方产品，也不隶属于美国国务院、CEAC、GTS、IRCC、韩国签证门户、中信银行或任何政府机构。只有在你理解并接受第三方自动查询、跨境数据传输及官网变动风险的前提下，才建议使用。

## 赞赏支持

CEACStatusBot 目前仍按非盈利个人项目维护。如果它确实帮你节省了时间、减少了盯状态的压力，欢迎自愿赞赏，用于覆盖服务器和日常维护成本。

联系邮箱：`ceac-admin@mikezhuang.cn`

<img src="frontend/public/support/buy-me-a-coffee.jpg" alt="支持 CEACStatusBot" width="180" />

## 产品概览

CEACStatusBot 想解决的不是“能不能查”，而是“能不能像一个完整产品一样稳定地查”。用户可以在一个界面里创建档案、发起查询、查看时间线、接收邮件、管理发信配置；管理员可以查看队列、管理账号等级、检查系统日志，并基于一套明确的生产安全基线完成部署。

## 支持的查询流

- 美国签证 CEAC 状态监控
- `Approved` 或 `Issued` 后的 GTS 护照预约 slot 监控
- 加拿大 IRCC Portal Alpha 监控
- 韩国签证门户状态查询
- 邮件通知、测试邮件、自定义 SMTP
- 多用户账号、账号等级、管理员后台

## 核心能力

- FastAPI 后端、SQLite 存储、APScheduler 调度、独立 Worker 消费队列
- React + Vite + TypeScript 前端，支持中文和英文界面
- 注册、邮箱验证码、忘记密码、条款同意、会话管理
- 自动监控、手动刷新任务、状态历史、查询日志
- 敏感字段、SMTP 凭证、IRCC 凭证、原始快照加密保存
- 管理员后台支持账号等级、Worker 优先级、队列可视化、安全事件和系统发信配置

## 查询模型

### 美国 CEAC

CEAC 档案支持定时查询和立即查询。状态变化或 CEAC 更新时间变化会写入历史，并可触发邮件通知。普通账号、Premium 账号和管理员使用不同的额度策略。

### GTS 护照预约 slot

GTS 监控绑定在 CEAC 档案下，功能目标只有“检测并通知”，不自动预约、不占位、不抢 slot。发现 slot 后查询频率会自动放缓，用户预约成功后可手动停止监控。

### 加拿大 IRCC Portal Alpha

IRCC 功能目前仍为 Alpha。系统会比较多类 IRCC 快照，记录可见状态变化，并在申请状态、消息或申请人侧生物信息发生变化时发送邮件。由于这一能力依赖用户授权提交的门户凭证，并且接入路径不是官方公开产品接口，因此只建议在你信任的部署环境中使用。

### 韩国签证门户

韩国签证监控使用当前门户查询链路。系统会把结构化状态结果和“暂无查询资料”都视为有效快照，以便后续追踪状态变化。

## 本地开发

安装后端依赖：

```bash
pip install uv
uv sync
cp .env.example .env
```

启动后端：

```bash
uv run uvicorn CEACStatusBot.web.main:app --host 127.0.0.1 --port 8000 --reload
```

另开一个终端启动 Worker：

```bash
uv run python -m CEACStatusBot.web.worker
```

启动前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。

## 关键配置

复制 `.env.example` 后，公网部署前至少需要重点检查这些配置：

- `SECRET_KEY`：会话签名密钥，生产必须更换
- `CREDENTIAL_KEY_FILE`：仓库外主密钥文件路径
- `DATABASE_PATH`：SQLite 数据库路径
- `COOKIE_SECURE=true`：HTTPS 生产环境必须开启
- `CORS_ORIGINS`、`CSRF_TRUSTED_ORIGINS`、`ALLOWED_HOSTS`：生产允许域名
- `SYSTEM_FROM_EMAIL` 及 SMTP 配置：系统默认发信能力

默认不会自动创建演示账号。如果只在本地开发时需要演示账号，可设置 `SEED_DEFAULT_USERS=true` 并提供 `DEFAULT_ADMIN_EMAIL`、`DEFAULT_ADMIN_PASSWORD`。公网环境必须保持关闭。

## 代码结构

- `CEACStatusBot/web/main.py`：FastAPI 应用与 API 路由
- `CEACStatusBot/web/worker.py`：独立任务消费进程
- `CEACStatusBot/web/case_service.py`：CEAC 与 GTS 档案逻辑
- `CEACStatusBot/web/ircc_portal_service.py`：IRCC 账号、快照与通知逻辑
- `CEACStatusBot/web/korea_visa_service.py`：韩国签证查询与历史逻辑
- `frontend/src/App.tsx`：前端主应用

## 安全说明

- 登录密码使用 Argon2id 哈希
- 敏感字段和原始快照使用 AES-256-GCM 加密
- 主密钥保存在仓库外
- 敏感请求校验 `Origin` / `Referer`
- 应用层启用请求体限制、Host 白名单、限流和安全事件审计
- 第三方查询目标固定，用户输入不能控制请求 Host

IRCC Portal Alpha 为了支持自动监控，会保存用户授权提交的门户凭证。它的信任要求高于普通 CEAC 查询，使用时请格外谨慎。

## 文档索引

- [DEPLOYMENT.md](DEPLOYMENT.md)：生产部署说明
- [OPERATIONS.md](OPERATIONS.md)：日常运维与排障
- [SECURITY.md](SECURITY.md)：安全模型与事件处置
- [SECURITY.en.md](SECURITY.en.md)：公开漏洞披露政策
- [THREAT_MODEL.md](THREAT_MODEL.md)：威胁模型
- [PRIVACY.md](PRIVACY.md)：数据保存与自托管责任
- [CONTRIBUTING.md](CONTRIBUTING.md)：贡献指南
- [ROADMAP.md](ROADMAP.md)：后续规划
- [CHANGELOG.md](CHANGELOG.md)：版本记录
- [LOCATION.md](LOCATION.md)：CEAC 办理地点参考
- [DESIGN.md](DESIGN.md)：界面与设计说明

## License

本项目遵循 [GNU General Public License v3.0](LICENSE)。

## 致谢

本项目基于 [Andision/CEACStatusBot](https://github.com/Andision/CEACStatusBot) 的部分思路和实现继续演进，并扩展成面向多用户的 Web 产品。

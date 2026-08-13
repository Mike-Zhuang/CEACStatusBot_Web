# CEACStatusBot Web

[![CI](https://github.com/Mike-Zhuang/CEACStatusBot_Web/actions/workflows/ci.yml/badge.svg)](https://github.com/Mike-Zhuang/CEACStatusBot_Web/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Mike-Zhuang/CEACStatusBot_Web/actions/workflows/codeql.yml/badge.svg)](https://github.com/Mike-Zhuang/CEACStatusBot_Web/actions/workflows/codeql.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](pyproject.toml)
[![Node 22](https://img.shields.io/badge/Node-22-339933.svg)](frontend/package.json)
[![GitHub stars](https://img.shields.io/github/stars/Mike-Zhuang/CEACStatusBot_Web?style=flat)](https://github.com/Mike-Zhuang/CEACStatusBot_Web/stargazers)

CEACStatusBot Web is a self-hosted visa status monitoring console for individuals and small operators. It combines U.S. visa CEAC status tracking, Canada IRCC Portal Alpha monitoring, Korea visa status checks, email notifications, account management, and an admin console in one deployable web application.

The public service is available at [ceac.mikezhuang.cn](https://ceac.mikezhuang.cn).

[中文文档](README.Chinese.md)

> This is a non-official product and is not affiliated with the U.S. Department of State, CEAC, GTS, IRCC, the Korea Visa Portal, CITIC Bank, or any government agency. Use it only if you understand and accept the risks of third-party query automation and cross-border data transmission.

## Support

CEACStatusBot is maintained as a nonprofit personal project. If it saves you time or reduces monitoring stress, voluntary support helps cover hosting and maintenance costs.

Contact: `ceac-admin@mikezhuang.cn`

<img src="frontend/public/support/buy-me-a-coffee.jpg" alt="Support CEACStatusBot" width="180" />

## Overview

CEACStatusBot is designed around one idea: visa monitoring should feel like a product, not a pile of scripts. The app gives users a single place to create profiles, trigger checks, review timelines, receive notifications, and manage sender settings. Operators get queue visibility, account controls, system logs, and a production-ready security baseline.

## Supported Flows

- U.S. visa CEAC status monitoring
- GTS passport appointment slot monitoring after `Approved` or `Issued`
- Canada IRCC Portal Alpha monitoring
- Korea Visa Portal status monitoring
- Email notifications, test emails, and custom SMTP settings
- Multi-user accounts, account tiers, linked-account review, and admin controls

## Product Highlights

- FastAPI backend with SQLite storage, APScheduler scheduling, and a standalone Worker queue consumer
- React + Vite + TypeScript frontend with Chinese and English UI
- Account registration, email verification, password reset, terms acceptance, and session management
- Automatic monitoring, manual refresh jobs, status timelines, and query history
- Encrypted storage for sensitive profile fields, SMTP credentials, IRCC credentials, and raw snapshots
- Admin console for account tiers, worker priority, queue visibility, security events, account restriction/appeals, linked-account quota enforcement, and sender configuration

## Query Models

### U.S. CEAC

CEAC profiles can run on schedule or on demand. Status changes and CEAC last-updated changes are written to history and can trigger notification emails. Standard and Premium accounts use different quotas, while admins are exempt.

For confirmed linked Standard accounts, an administrator can apply a shared quota to prevent multi-account limit evasion. A review-only association does not change an existing user's quota by itself.

### GTS passport appointment slots

GTS monitoring is linked to a CEAC profile and is intended only for detection and notification. It does not book, hold, or grab slots. Once a slot is detected, polling slows down; users can stop monitoring after they complete booking.

### Canada IRCC Portal Alpha

IRCC support is currently marked Alpha. The app compares multiple IRCC snapshots, records visible changes, and can send notification emails when application status, messages, or applicant-side biometric details change. Because IRCC access relies on user-authorized credentials and an unofficial integration path, this flow should be used carefully and only on deployments you trust.

### Korea Visa Portal

Korea monitoring supports the current portal-based status lookup flow and records either structured status fields or the portal's "no data found" state as a valid snapshot.

## Local Development

Install backend dependencies:

```bash
pip install uv
uv sync
cp .env.example .env
```

Start the backend:

```bash
uv run uvicorn CEACStatusBot.web.main:app --host 127.0.0.1 --port 8000 --reload
```

Start the Worker in another terminal:

```bash
uv run python -m CEACStatusBot.web.worker
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Essential Configuration

Copy `.env.example` and review these values before any public deployment:

- `SECRET_KEY`: session signing secret; must be changed in production
- `CREDENTIAL_KEY_FILE`: path to the repository-external credential master key
- `DATABASE_PATH`: SQLite database location
- `COOKIE_SECURE=true`: required behind HTTPS
- `CORS_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `ALLOWED_HOSTS`: production host allowlists
- `SYSTEM_FROM_EMAIL` and SMTP settings: default sender configuration

Demo accounts are disabled by default. If you need local-only seeded users, set `SEED_DEFAULT_USERS=true` and provide `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD`. Keep this disabled on public deployments.

## Architecture

- `CEACStatusBot/web/main.py`: FastAPI application and API routes
- `CEACStatusBot/web/worker.py`: standalone queue consumer
- `CEACStatusBot/web/case_service.py`: CEAC and GTS case logic
- `CEACStatusBot/web/ircc_portal_service.py`: IRCC account, snapshot, and notification logic
- `CEACStatusBot/web/korea_visa_service.py`: Korea visa query and history logic
- `frontend/src/App.tsx`: main frontend application

## Security Notes

- Passwords use Argon2id hashing
- Sensitive fields and raw snapshots are encrypted with AES-256-GCM
- The credential master key is stored outside the repository
- Sensitive requests validate `Origin` and `Referer`
- Request size limits, host allowlists, rate limits, and security-event logging are enabled
- Third-party query targets are fixed; user input does not control request hosts
- Restricting an account revokes active sessions, pauses CEAC/GTS/IRCC/Korea automatic work, fails queued jobs, and suppresses in-flight result persistence before it can notify
- Restricted users retain their data, receive a neutral notice at their registered email, and can submit an appeal from a limited account page; restoring access never silently restarts monitoring

IRCC Portal Alpha stores user-authorized portal credentials to support scheduled monitoring. That is a higher-trust feature than plain CEAC polling. Treat it accordingly.

## Repository Metrics

![Repository clone history](https://raw.githubusercontent.com/Mike-Zhuang/CEACStatusBot_Web/repo-metrics/clone-history.svg)

The clone chart is generated from GitHub Traffic API aggregates and preserved on the independent `repo-metrics` branch. Clone counts can include bots, CI jobs, and repeated pulls. They are operational signals, not verified user counts.

## Documentation Map

- [DEPLOYMENT.md](DEPLOYMENT.md): production deployment
- [OPERATIONS.md](OPERATIONS.md): day-2 operations and troubleshooting
- [SECURITY.md](SECURITY.md): security model and incident handling
- [SECURITY.en.md](SECURITY.en.md): public vulnerability disclosure policy
- [THREAT_MODEL.md](THREAT_MODEL.md): assets, trust boundaries, and controls
- [PRIVACY.md](PRIVACY.md): stored data and self-hosting responsibilities
- [CONTRIBUTING.md](CONTRIBUTING.md): contributor workflow
- [ROADMAP.md](ROADMAP.md): planned work
- [CHANGELOG.md](CHANGELOG.md): release notes
- [LOCATION.md](LOCATION.md): CEAC location references
- [DESIGN.md](DESIGN.md): UI and design notes

## License

This project is released under the [GNU General Public License v3.0](LICENSE).

## Acknowledgements

This project builds on ideas and parts of the original [Andision/CEACStatusBot](https://github.com/Andision/CEACStatusBot), then extends them into a multi-user web product.

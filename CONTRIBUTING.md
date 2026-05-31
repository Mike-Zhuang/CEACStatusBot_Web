# Contributing to CEACStatusBot Web

Thank you for helping improve CEACStatusBot Web. This repository handles sensitive visa-related data, so small, reviewable changes are preferred.

## Development Setup

```bash
pip install uv
uv sync --locked --group dev
cp .env.example .env
cd frontend && npm ci
```

Run the backend, Worker, and frontend in separate terminals:

```bash
uv run uvicorn CEACStatusBot.web.main:app --host 127.0.0.1 --port 8000 --reload
uv run python -m CEACStatusBot.web.worker
cd frontend && npm run dev
```

## Required Checks

```bash
uv run --locked --group dev ruff check CEACStatusBot tests scripts
uv run --locked --group dev pytest
python scripts/check_repository_hygiene.py
cd frontend && npm run build
git diff --check
```

## Pull Requests

- Keep changes focused and explain user-visible behavior.
- Add tests for authentication, encryption, outbound requests, or query parsing changes.
- Mock all third-party portals in automated tests.
- Do not commit databases, logs, cookies, screenshots containing personal data, credentials, or production environment files.
- Do not change the production deployment chain without documenting migration and rollback steps.

## Security Changes

Read [SECURITY.en.md](SECURITY.en.md), [THREAT_MODEL.md](THREAT_MODEL.md), and [PRIVACY.md](PRIVACY.md) before modifying encryption, sessions, portal credentials, mail delivery, or outbound request targets.

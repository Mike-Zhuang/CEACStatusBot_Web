# Agent Maintenance Guide

This file defines safety boundaries for AI-assisted repository maintenance.

## Rules

- Never commit production databases, environment files, credential keys, cookies, screenshots containing personal data, logs, or real portal credentials.
- Preserve the existing systemd and Baota sync-script deployment chain unless a maintainer explicitly requests a migration.
- Mock CEAC, GTS, IRCC Portal, Korea Visa Portal, SMTP, and GitHub Traffic API requests in tests.
- Keep outbound request hosts fixed in code. Do not allow profile fields to override scheme, host, or base URL.
- Preserve the support QR code at `frontend/public/support/buy-me-a-coffee.jpg`.
- Preserve `captcha.onnx`; it is required at runtime for CEAC captcha recognition.
- Treat IRCC Portal credentials and raw snapshots as sensitive data.
- Run repository hygiene checks, backend tests, frontend build, and `git diff --check` before proposing a merge.

## Deployment Compatibility

Production currently runs `uv sync`, `npm ci --no-audit --no-fund`, `npm run build`, frontend `rsync`, and systemd restarts. New dependency groups must remain opt-in so production `uv sync` installs runtime dependencies only.

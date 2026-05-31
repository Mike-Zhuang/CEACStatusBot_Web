# Release Checklist

## Repository

- [ ] Confirm no databases, secrets, logs, cookies, personal screenshots, or production environment files are tracked.
- [ ] Run `python scripts/check_repository_hygiene.py`.
- [ ] Review dependency and lockfile changes.

## Verification

- [ ] Run `uv sync --locked --group dev`.
- [ ] Run `uv run --locked --group dev ruff check CEACStatusBot tests scripts`.
- [ ] Run `uv run --locked --group dev pytest`.
- [ ] Run `uv sync --locked --no-default-groups`.
- [ ] Run `cd frontend && npm ci && npm run build`.
- [ ] Run `git diff --check`.

## Deployment

- [ ] Back up the SQLite database and credential master key.
- [ ] Confirm the systemd + Baota sync-script path is unchanged.
- [ ] Verify `https://ceac.mikezhuang.cn/api/health`.
- [ ] Check backend and Worker service status.
- [ ] Smoke-test login, admin queue view, and CEAC, IRCC, and Korea profile pages.

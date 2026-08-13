# Security

This document records the production security model, boundaries, and operational requirements for CEACStatusBot Web. Do not commit real administrator accounts, SMTP credentials, databases, master keys, or server private keys.

## Reporting a Vulnerability

Do not disclose vulnerabilities, credentials, or personal data in a public Issue. Use [GitHub Private Vulnerability Reporting](https://github.com/Mike-Zhuang/CEACStatusBot_Web/security/advisories/new).

Do not include real passport numbers, visa application numbers, portal credentials, cookies, SMTP passwords, databases, screenshots containing personal data, or production logs unless the maintainer explicitly requests a minimal encrypted sample.

## Security Model

- Login passwords use one-way Argon2id hashes. Legacy PBKDF2-SHA256 hashes are accepted only for migration and should be upgraded after a successful login.
- Sensitive CEAC profile fields, GTS UID/HAL identifiers, IRCC Portal email/password/token caches, user SMTP credentials, system SMTP credentials, and raw snapshots use reversible AES-256-GCM encryption.
- The reversible-encryption master key is stored outside the repository and configured through `CREDENTIAL_KEY_FILE`.
- The web process does not run CEAC scraping directly. It creates SQLite queue jobs that are consumed by a standalone Worker.
- Outbound targets are fixed in code: `https://ceac.state.gov`, `https://scheduling-api.gtspremium.com`, `https://portal-portail.apps.cic.gc.ca`, `https://api.portal-portail.apps.cic.gc.ca`, and `https://www.visa.go.kr`. User input cannot override request host, scheme, or base URL.
- Sensitive mutation APIs validate `Origin` / `Referer`. Production should trust only `https://ceac.mikezhuang.cn`.
- Production cookies must use `HttpOnly + SameSite=Lax + Secure`.
- The application issues an anonymous device cookie and persists hashed IP/device/account/email identifiers for throttling, login cooldowns, verification-code limits, and security-event auditing.
- When traffic reaches the app through a trusted reverse proxy, the application prefers a validated `X-Real-IP`; it does not trust the first client-supplied `X-Forwarded-For` value.
- Sessions are stored in the database. Cookies contain only random session tokens. Server-side revocation, idle expiry, and absolute expiry are supported.
- An account restriction revokes active sessions, disables CEAC/GTS/IRCC/Korea automatic monitoring, fails queued jobs, and rechecks account state before an in-flight third-party response can be persisted or emailed. Profile data is retained for appeal and recovery.
- API request bodies are size-limited. Host headers and security response headers are also enforced.
- Browser-side password remembering is a convenience trade-off and should be used only on private devices.
- Public traffic must use the HTTPS domain. Port `8010` is not a public entry point.

## Boundaries and Trade-offs

This project does not depend on a paid cloud KMS or paid WAF. It uses a local key file, Linux permissions, Nginx throttling, and application-level validation.

- A repository leak does not expose the runtime database, `backend.env`, or master key.
- A SQLite backup leak does not directly expose sensitive fields if the master key remains private.
- A regular configuration leak does not directly decrypt sensitive fields if the external master-key file remains private.
- Full root compromise can expose the local master-key file. This is not equivalent to cloud-KMS isolation.
- IRCC Portal Alpha stores user-authorized portal credentials for scheduled checks. It requires more trust than single-request CEAC, GTS, or Korea lookups and should be enabled only on trusted deployments.

## Master Key File

Recommended production path:

```bash
/opt/ceacstatusbot-runtime/secrets/credential-master.key
```

Generate a key:

```bash
install -d -m 750 -o root -g www /opt/ceacstatusbot-runtime/secrets
python - <<'PY'
import base64
import os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
```

Set file ownership and permissions:

```bash
chown root:www /opt/ceacstatusbot-runtime/secrets/credential-master.key
chmod 0440 /opt/ceacstatusbot-runtime/secrets/credential-master.key
```

Store only the path in `backend.env`:

```bash
CREDENTIAL_KEY_FILE=/opt/ceacstatusbot-runtime/secrets/credential-master.key
```

## Key Rotation

Back up the database and old key before rotating credentials:

1. Stop the Worker to prevent writes during migration.
2. Back up SQLite, the old master key, and `backend.env`.
3. Generate a new master-key file.
4. Run the credential re-encryption migration.
5. Restart the backend and Worker.
6. Smoke-test system SMTP, user SMTP, and CEAC profile queries.
7. Archive the old key only after confirming that the new backup is restorable.

Never delete the old key without a complete backup.

## Sessions and CSRF

Production must configure:

```bash
COOKIE_SECURE=true
CSRF_TRUSTED_ORIGINS=https://ceac.mikezhuang.cn
CORS_ORIGINS=https://ceac.mikezhuang.cn
ALLOWED_HOSTS=ceac.mikezhuang.cn,localhost,127.0.0.1
TRUSTED_PROXY_IPS=127.0.0.1,::1
SESSION_IDLE_TIMEOUT_MINUTES=720
SESSION_ABSOLUTE_TIMEOUT_DAYS=14
```

Mutation endpoints, including login, registration, password reset, profile saves, SMTP saves, manual queries, test emails, and administrator configuration, must continue to validate `Origin` / `Referer`.

GTS UID/HAL configuration and manual slot checks are also sensitive. Only normalized identifiers may be sent to the fixed GTS API host.

## Rate Limits and Auditing

The backend records `security_events` for login failures, cooldowns, verification-code throttling, CSRF rejection, oversized bodies, invalid sessions, and administrator-sensitive actions. IP, device, and email identifiers are hashed with a `SECRET_KEY`-derived value before persistence.

Default throttling policy:

- Login attempts are limited by IP/device. Repeated email failures trigger cooldowns.
- Registration and password-reset codes are limited by email and IP/device.
- Authenticated APIs are limited by account and device, with separate Standard, Premium, and administrator quotas.
- Manual CEAC/GTS/IRCC/Korea queries and business emails retain account-level daily quotas. Administrators can apply a shared Standard quota only to confirmed linked-account groups; review-only groups do not change existing quotas.
- Restricted accounts receive a neutral registered-email notice and may submit an appeal through the limited account page. Restoring access leaves all monitoring paused until the user explicitly re-enables it.

## Nginx Baseline

Production Nginx should enable:

- HTTPS redirects
- `ssl_protocols TLSv1.2 TLSv1.3`
- HSTS
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- A baseline Content Security Policy
- `client_header_timeout`, `client_body_timeout`, and `send_timeout`
- `limit_req` for login, registration, verification-code, and API routes
- `limit_conn` per IP

Port `8010` should remain internal or be retired.

## Incident Response

If a leak is suspected:

1. Stop the backend and Worker immediately.
2. Back up current SQLite, logs, and configuration for audit purposes.
3. Rotate `SECRET_KEY` to invalidate sessions.
4. Rotate `credential-master.key` and re-encrypt sensitive fields.
5. Reset system and user SMTP credentials.
6. Review administrator accounts, users, query logs, and system access logs.
7. Restart services and verify health, login, manual query, and email flows.

If server root access may have been compromised, treat the master key as exposed and rotate server login keys, backup keys, and third-party credentials.

The repository threat model is documented in [THREAT_MODEL.md](THREAT_MODEL.md).

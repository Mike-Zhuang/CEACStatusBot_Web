# Threat Model

## Scope

CEACStatusBot Web is a self-hosted monitoring console. It stores user accounts and visa-related profile data, schedules portal checks, and sends email notifications.

## Assets

- Login sessions and account roles
- Visa profile identifiers and raw query snapshots
- IRCC Portal credentials and token caches
- SMTP credentials
- SQLite runtime data and the repository-external credential master key

## Trust Boundaries

- Browser to FastAPI API over HTTPS
- FastAPI API to SQLite runtime storage
- Worker to CEAC, GTS, IRCC Portal, and Korea Visa Portal
- Backend to SMTP providers
- Git repository to the production sync script

## Primary Threats and Controls

| Threat | Controls |
| --- | --- |
| Repository leak | Runtime database, logs, environment files, and credential keys are ignored and rejected by CI hygiene checks. |
| Database leak | Sensitive fields and raw snapshots use AES-256-GCM with a repository-external master key. |
| Credential stuffing | Argon2id passwords, login throttling, cooldowns, and server-side sessions. |
| CSRF | Trusted `Origin` / `Referer` validation on mutation APIs and `SameSite=Lax` cookies. |
| SSRF through profile input | Portal request hosts are fixed in code; user input is encoded as request data or parameters. |
| Excessive polling | Scheduled queues, account quotas, rate limits, and operator visibility. |
| Sensitive public disclosure | Private vulnerability reporting guidance and Issue templates that prohibit personal data. |

## Non-goals

- This project is not a cloud KMS or hardened multi-tenant SaaS platform.
- Root compromise of a self-hosted server can expose runtime secrets.
- Third-party portals can change behavior, block traffic, or become unavailable.
- Monitoring does not guarantee appointment availability, processing success, or notification delivery.

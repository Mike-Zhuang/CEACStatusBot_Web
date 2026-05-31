# Privacy

CEACStatusBot Web is self-hosted software. Operators are responsible for lawful use, data retention, access control, backups, and disclosure to their users.

## Stored Data

Depending on enabled features, a deployment can store:

- Account email, password hash, role, preferences, and sessions
- CEAC, GTS, IRCC Portal, and Korea Visa Portal profile data
- Encrypted raw snapshots and status history
- Encrypted SMTP credentials
- IRCC Portal credentials and token caches for scheduled monitoring
- Security-event hashes, queue metadata, and email delivery metadata

## Purpose

Data is used only to run monitoring, display history, enforce quotas, deliver notifications, and support operator troubleshooting.

## Retention

The current account cleanup policy sends an inactivity notice after about 15 days without relevant CEAC, GTS, IRCC, or Korea status activity and deletes eligible inactive non-admin accounts after about 30 days. Administrator accounts are exempt. Operators should review this policy for their deployment.

## Third Parties

Portal checks send the minimum required query data to the selected external portal. Email notifications send message content through the configured SMTP provider. Review notification content and SMTP provider policies before enabling email.

## Self-hosting Responsibilities

- Store the SQLite database and credential master key outside the repository.
- Restrict access to runtime files and backups.
- Use HTTPS and production host allowlists.
- Tell users which portal integrations are enabled.
- Remove data when it is no longer needed.

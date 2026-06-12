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

The current account cleanup policy sends an empty-account notice when a non-admin account still has no CEAC, IRCC, or Korea application profile about 15 days after registration, and deletes that empty account after about 30 days if it still has no application profile and was already warned. Accounts with at least one application profile are retained permanently by this cleanup job. Administrator accounts are exempt. Operators should review this policy for their deployment.

## Third Parties

Portal checks send the minimum required query data to the selected external portal. Email notifications send message content through the configured SMTP provider. Review notification content and SMTP provider policies before enabling email.

## Self-hosting Responsibilities

- Store the SQLite database and credential master key outside the repository.
- Restrict access to runtime files and backups.
- Use HTTPS and production host allowlists.
- Tell users which portal integrations are enabled.
- Remove data when it is no longer needed.

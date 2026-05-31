# Security Policy

## Reporting a Vulnerability

Please do not open a public issue for vulnerabilities. Use [GitHub Private Vulnerability Reporting](https://github.com/Mike-Zhuang/CEACStatusBot_Web/security/advisories/new).

Do not include real passport numbers, visa application numbers, portal credentials, cookies, SMTP passwords, databases, screenshots containing personal data, or production logs unless the maintainer explicitly requests a minimal encrypted sample.

## Sensitive Areas

- Credential encryption and key loading
- Authentication, sessions, CSRF validation, and rate limits
- CEAC, GTS, IRCC Portal, and Korea Visa Portal outbound requests
- Email delivery and SMTP credential storage
- Worker queue processing and account cleanup

## Response Process

1. The maintainer confirms receipt and triages impact.
2. A private fix is prepared with regression coverage.
3. Deployment and rollback steps are reviewed.
4. A release is published after affected operators have a reasonable remediation path.

The detailed production security model is documented in [SECURITY.md](SECURITY.md). The repository threat model is documented in [THREAT_MODEL.md](THREAT_MODEL.md).

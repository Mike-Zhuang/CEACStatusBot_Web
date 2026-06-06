#!/usr/bin/env python3
"""Smoke-test seeded UI review data through the live API."""

from __future__ import annotations

import json

import httpx

BASE = "http://127.0.0.1:8000"
ORIGIN = "http://127.0.0.1:5173"
USER = ("user@local.review", "ReviewUser!123")
ADMIN = ("admin@local.review", "ReviewAdmin!123")


def login(client: httpx.Client, email: str, password: str) -> None:
    response = client.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN},
    )
    response.raise_for_status()


def main() -> int:
    issues: list[str] = []
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        login(client, *USER)
        ceacCases = client.get(f"{BASE}/api/cases", headers={"Origin": ORIGIN}).json().get("cases") or []
        irccCases = client.get(f"{BASE}/api/ircc/cases", headers={"Origin": ORIGIN}).json().get("cases") or []
        koreaCases = client.get(f"{BASE}/api/korea/cases", headers={"Origin": ORIGIN}).json().get("cases") or []
        if len(ceacCases) < 2:
            issues.append(f"expected >=2 CEAC cases, got {len(ceacCases)}")
        if len(irccCases) < 2:
            issues.append(f"expected >=2 IRCC cases, got {len(irccCases)}")
        if len(koreaCases) < 2:
            issues.append(f"expected >=2 Korea cases, got {len(koreaCases)}")
        if not any(case.get("lastStatus") == "Issued" for case in ceacCases):
            issues.append("missing CEAC Issued status in seed data")
        if not any(case.get("statusOverview") for case in irccCases):
            issues.append("missing IRCC statusOverview in seed data")

        login(client, *ADMIN)
        adminUsers = client.get(f"{BASE}/api/admin/users", headers={"Origin": ORIGIN})
        adminUsers.raise_for_status()
        users = adminUsers.json().get("users") or []
        if len(users) < 2:
            issues.append(f"expected >=2 admin users, got {len(users)}")

        queryRuns = client.get(f"{BASE}/api/admin/query-runs?limit=20", headers={"Origin": ORIGIN})
        queryRuns.raise_for_status()
        if not queryRuns.json().get("runs"):
            issues.append("admin query runs empty")

        deliveries = client.get(f"{BASE}/api/admin/email-deliveries?limit=20", headers={"Origin": ORIGIN})
        deliveries.raise_for_status()
        if not deliveries.json().get("deliveries"):
            issues.append("admin email deliveries empty")

    if issues:
        print("UI review API smoke test failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("UI review API smoke test passed.")
    print(json.dumps({
        "ceacCases": len(ceacCases),
        "irccCases": len(irccCases),
        "koreaCases": len(koreaCases),
        "adminUsers": len(users),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

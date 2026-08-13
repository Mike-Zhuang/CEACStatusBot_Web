from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from CEACStatusBot.web.main import app
from CEACStatusBot.web.security_guard import enforceAuthCodeLimits, enforceRateLimit, requestIp


def buildRequest() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/send-code",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
    )


def test_protected_and_admin_routes_enforce_permissions(createUser) -> None:
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/api/cases").status_code == 401
    createUser()
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost"},
        json={"email": "user@example.com", "password": "correct-password"},
    )
    assert login.status_code == 200
    assert client.get("/api/admin/users").status_code == 403


def test_mutation_routes_require_trusted_origin() -> None:
    client = TestClient(app, base_url="http://localhost")
    payload = {"email": "nobody@example.com", "password": "wrong-password"}

    assert client.post("/api/auth/login", json=payload).status_code == 403
    assert client.post("/api/auth/login", headers={"Origin": "https://evil.example"}, json=payload).status_code == 403
    assert client.post("/api/auth/login", headers={"Origin": "http://localhost"}, json=payload).status_code == 401


def test_generic_rate_limit_rejects_excess_requests() -> None:
    request = buildRequest()
    enforceRateLimit(request=request, scope="test", subject="subject", limit=1, windowSeconds=60)
    with pytest.raises(HTTPException) as excInfo:
        enforceRateLimit(request=request, scope="test", subject="subject", limit=1, windowSeconds=60)
    assert excInfo.value.status_code == 429


def test_auth_code_rate_limit_rejects_excess_requests() -> None:
    request = buildRequest()
    for _ in range(3):
        enforceAuthCodeLimits(request, "person@example.test", "register")
    with pytest.raises(HTTPException) as excInfo:
        enforceAuthCodeLimits(request, "person@example.test", "register")
    assert excInfo.value.status_code == 429


def test_trusted_proxy_prefers_valid_x_real_ip_over_client_supplied_forwarded_for() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/health",
            "headers": [
                (b"x-forwarded-for", b"198.51.100.99, 203.0.113.10"),
                (b"x-real-ip", b"203.0.113.10"),
            ],
            "client": ("127.0.0.1", 1234),
        }
    )
    assert requestIp(request) == "203.0.113.10"


def test_trusted_proxy_forwarded_for_fallback_uses_last_valid_hop() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/health",
            "headers": [(b"x-forwarded-for", b"forged-value, 198.51.100.99, 203.0.113.10")],
            "client": ("127.0.0.1", 1234),
        }
    )
    assert requestIp(request) == "203.0.113.10"

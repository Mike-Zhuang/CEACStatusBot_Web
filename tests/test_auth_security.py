from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from CEACStatusBot.web.database import getConnection
from CEACStatusBot.web.security import (
    SESSION_COOKIE_NAME,
    clearSessionCookie,
    getCurrentUser,
    hashLegacyPassword,
    hashPassword,
    setSessionCookie,
    verifyPassword,
)


def buildRequest(cookie: str = "") -> Request:
    headers = [(b"user-agent", b"pytest")]
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE_NAME}={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/api/me", "headers": headers, "client": ("127.0.0.1", 1234)})


def readSessionCookie(response: Response) -> str:
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    return cookies[SESSION_COOKIE_NAME].value


def test_argon2id_and_legacy_pbkdf2_passwords_verify() -> None:
    assert verifyPassword("correct-password", hashPassword("correct-password"))
    assert verifyPassword("correct-password", hashLegacyPassword("correct-password"))
    assert not verifyPassword("wrong-password", hashPassword("correct-password"))


def test_session_can_be_created_and_revoked(createUser) -> None:
    user = createUser()
    response = Response()
    setSessionCookie(response, user, buildRequest())
    token = readSessionCookie(response)
    request = buildRequest(token)

    assert getCurrentUser(request)["id"] == user["id"]

    clearSessionCookie(Response(), request)
    with pytest.raises(HTTPException) as excInfo:
        getCurrentUser(request)
    assert excInfo.value.status_code == 401


def test_idle_session_expires(createUser) -> None:
    user = createUser()
    response = Response()
    setSessionCookie(response, user, buildRequest())
    token = readSessionCookie(response)
    with getConnection() as connection:
        connection.execute(
            "UPDATE user_sessions SET last_seen_at = ?",
            ((datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0).isoformat(),),
        )

    with pytest.raises(HTTPException) as excInfo:
        getCurrentUser(buildRequest(token))
    assert excInfo.value.status_code == 401

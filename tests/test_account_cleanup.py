from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from CEACStatusBot.web.database import getConnection, initializeDatabase
from CEACStatusBot.web import main


def isoDaysAgo(days: int) -> str:
    return (datetime.now(UTC).replace(microsecond=0) - timedelta(days=days)).isoformat()


def setUserCreatedAt(userId: int, daysAgo: int, noticeDaysAgo: int | None = None) -> None:
    createdAt = isoDaysAgo(daysAgo)
    noticeSentAt = isoDaysAgo(noticeDaysAgo) if noticeDaysAgo is not None else None
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE users
            SET created_at = ?,
                updated_at = ?,
                inactivity_notice_sent_at = ?
            WHERE id = ?
            """,
            (createdAt, createdAt, noticeSentAt, userId),
        )


def addCeacCase(userId: int) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    with getConnection() as connection:
        connection.execute(
            """
            INSERT INTO ceac_cases (
                user_id, display_name, location, application_num, passport_number, surname,
                receive_email, created_at, updated_at
            )
            VALUES (?, 'test case', 'Shanghai', 'AA00TEST', 'P0000000', 'TEST', 'user@example.com', ?, ?)
            """,
            (userId, now, now),
        )


def markUserHadApplicationProfile(userId: int) -> None:
    with getConnection() as connection:
        connection.execute("UPDATE users SET has_application_profile_history = 1 WHERE id = ?", (userId,))


def getUser(userId: int) -> dict[str, Any] | None:
    with getConnection() as connection:
        return connection.execute("SELECT * FROM users WHERE id = ?", (userId,)).fetchone()


def testEmptyRegisteredAccountGetsNoticeAfterFifteenDays(createUser, monkeypatch) -> None:
    user = createUser()
    setUserCreatedAt(int(user["id"]), main.INACTIVITY_NOTICE_DAYS + 1)
    sentEmails: list[tuple[str, str, str]] = []
    monkeypatch.setattr(main, "sendSystemEmail", lambda *args: sentEmails.append(args))

    main.processInactiveAccounts()

    updatedUser = getUser(int(user["id"]))
    assert updatedUser is not None
    assert updatedUser["inactivity_notice_sent_at"]
    assert len(sentEmails) == 1
    assert sentEmails[0][1] == "CEACStatusBot 空账号删除提醒"


def testEmptyWarnedAccountDeletesAfterThirtyDays(createUser, monkeypatch) -> None:
    user = createUser()
    setUserCreatedAt(int(user["id"]), main.INACTIVITY_DELETE_DAYS + 1, noticeDaysAgo=10)
    sentEmails: list[tuple[str, str, str]] = []
    monkeypatch.setattr(main, "sendSystemEmail", lambda *args: sentEmails.append(args))

    main.processInactiveAccounts()

    assert getUser(int(user["id"])) is None
    assert len(sentEmails) == 1
    assert sentEmails[0][1] == "CEACStatusBot 空账号已自动删除"


def testWarnedAccountWithApplicationProfileIsKeptAndNoticeCleared(createUser, monkeypatch) -> None:
    user = createUser()
    setUserCreatedAt(int(user["id"]), main.INACTIVITY_DELETE_DAYS + 1, noticeDaysAgo=10)
    addCeacCase(int(user["id"]))
    sentEmails: list[tuple[str, str, str]] = []
    monkeypatch.setattr(main, "sendSystemEmail", lambda *args: sentEmails.append(args))

    main.processInactiveAccounts()

    updatedUser = getUser(int(user["id"]))
    assert updatedUser is not None
    assert updatedUser["inactivity_notice_sent_at"] is None
    assert sentEmails == []


def testWarnedAccountThatEverAddedApplicationProfileIsKept(createUser, monkeypatch) -> None:
    user = createUser()
    setUserCreatedAt(int(user["id"]), main.INACTIVITY_DELETE_DAYS + 1, noticeDaysAgo=10)
    markUserHadApplicationProfile(int(user["id"]))
    sentEmails: list[tuple[str, str, str]] = []
    monkeypatch.setattr(main, "sendSystemEmail", lambda *args: sentEmails.append(args))

    main.processInactiveAccounts()

    updatedUser = getUser(int(user["id"]))
    assert updatedUser is not None
    assert updatedUser["inactivity_notice_sent_at"] is None
    assert sentEmails == []


def testInitializeDatabaseBackfillsExistingApplicationProfileHistory(createUser) -> None:
    user = createUser()
    addCeacCase(int(user["id"]))

    initializeDatabase()

    updatedUser = getUser(int(user["id"]))
    assert updatedUser is not None
    assert int(updatedUser["has_application_profile_history"]) == 1

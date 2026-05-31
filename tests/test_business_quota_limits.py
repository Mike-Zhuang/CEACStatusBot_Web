from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from CEACStatusBot.web.database import getConnection
from CEACStatusBot.web.mailer import DailyEmailLimitExceeded, enforceDailyEmailLimit, recordEmailDelivery
from CEACStatusBot.web.main import enforceDailyManualQueryLimit


def test_manual_query_limit_counts_existing_ceac_job(createUser) -> None:
    user = createUser()
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    with getConnection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO ceac_cases (
                user_id, display_name, location, application_num, passport_number, surname,
                receive_email, created_at, updated_at
            )
            VALUES (?, 'test', 'Shanghai', 'AA00TEST', 'P0000000', 'TEST', 'user@example.com', ?, ?)
            """,
            (user["id"], now, now),
        )
        connection.execute(
            """
            INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, 'manual', 'queued', ?, ?)
            """,
            (cursor.lastrowid, now, now),
        )

    with pytest.raises(HTTPException) as excInfo:
        enforceDailyManualQueryLimit(user)
    assert excInfo.value.status_code == 429


def test_daily_email_limit_counts_delivery_log(createUser) -> None:
    user = createUser()
    for index in range(5):
        recordEmailDelivery(
            userId=int(user["id"]),
            caseId=None,
            emailType="test",
            recipient="user@example.com",
            subject=f"test {index}",
        )

    with pytest.raises(DailyEmailLimitExceeded):
        enforceDailyEmailLimit(int(user["id"]))

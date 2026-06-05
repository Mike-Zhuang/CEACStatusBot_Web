from __future__ import annotations

from typing import Any

from CEACStatusBot.web.database import getConnection
from CEACStatusBot.web.korea_visa_service import createKoreaCase, getKoreaCase, listKoreaHistory, runKoreaCaseQuery, sendKoreaNotification
from CEACStatusBot.web.schemas import KoreaCaseInput


def createKoreaProfile(userId: int) -> dict[str, Any]:
    return createKoreaCase(
        userId,
        KoreaCaseInput(
            displayName="Korea test profile",
            passportNumber="P1234567",
            englishName="TEST USER",
            birthDate="2000-01-01",
            receiveEmail=None,
            senderMode="system",
            isEnabled=True,
            emailNotificationsEnabled=False,
            smtpConfig=None,
        ),
    )


def issuedResult() -> dict[str, Any]:
    return {
        "success": True,
        "application_no": "0600000000000",
        "application_date": "",
        "entry_purpose": "观光.过境",
        "visa_type": "多次",
        "stay_qualification": "C-3-9",
        "entry_expiry_date": "(2036.06.04.)",
        "visa_certificate_available": True,
        "status": "签发 (2026.06.04.)",
        "description": "",
        "no_data": False,
    }


def pendingResult() -> dict[str, Any]:
    return {
        "success": True,
        "application_no": "0600000000000",
        "application_date": "",
        "entry_purpose": "观光.过境",
        "visa_type": "",
        "stay_qualification": "",
        "entry_expiry_date": "",
        "visa_certificate_available": False,
        "status": "审核中",
        "description": "",
        "no_data": False,
    }


def datedReviewResult() -> dict[str, Any]:
    result = pendingResult()
    result["status"] = "审核中 (2026.06.04.)"
    return result


def test_korea_dated_review_email_includes_support(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fakeSendCaseEmail(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("CEACStatusBot.web.korea_visa_service.sendCaseEmail", fakeSendCaseEmail)

    sendKoreaNotification(
        {
            "display_name": "Korea test profile",
            "passport_number": "P1234567",
            "english_name": "TEST USER",
        },
        None,
        datedReviewResult(),
    )

    assert captured["emailType"] == "korea_status"
    assert captured["includeSupport"] is True


def test_korea_terminal_result_stops_automatic_query(monkeypatch, createUser) -> None:
    user = createUser(accountTier="premium")
    profile = createKoreaProfile(int(user["id"]))
    monkeypatch.setattr("CEACStatusBot.web.korea_visa_service.queryKoreaVisaStatus", lambda *args: issuedResult())

    result = runKoreaCaseQuery(int(profile["id"]), "korea_automatic")

    case = getKoreaCase(int(profile["id"]), int(user["id"]))
    history = listKoreaHistory(int(profile["id"]), int(user["id"]))
    assert result["success"] is True
    assert result["changed"] is True
    assert case is not None
    assert case["isEnabled"] is False
    assert case["nextCheckAt"] is None
    assert case["lastStatus"] == "签发 (2026.06.04.)"
    assert case["lastVisaType"] == "多次"
    assert case["lastStayQualification"] == "C-3-9"
    assert case["lastEntryExpiryDate"] == "(2036.06.04.)"
    assert case["lastVisaCertificateAvailable"] is True
    assert len(history) == 1
    assert history[0]["visaType"] == "多次"
    assert history[0]["visaCertificateAvailable"] is True


def test_korea_terminal_repeat_does_not_add_history_but_stays_stopped(monkeypatch, createUser) -> None:
    user = createUser(accountTier="premium")
    profile = createKoreaProfile(int(user["id"]))
    monkeypatch.setattr("CEACStatusBot.web.korea_visa_service.queryKoreaVisaStatus", lambda *args: issuedResult())

    runKoreaCaseQuery(int(profile["id"]), "korea_automatic")
    with getConnection() as connection:
        connection.execute(
            "UPDATE korea_cases SET is_enabled = 1, next_check_at = ? WHERE id = ?",
            ("2099-01-01T00:00:00+00:00", profile["id"]),
        )
    result = runKoreaCaseQuery(int(profile["id"]), "korea_automatic")

    case = getKoreaCase(int(profile["id"]), int(user["id"]))
    history = listKoreaHistory(int(profile["id"]), int(user["id"]))
    assert result["success"] is True
    assert result["changed"] is False
    assert case is not None
    assert case["isEnabled"] is False
    assert case["nextCheckAt"] is None
    assert len(history) == 1


def test_korea_non_terminal_result_keeps_automatic_query(monkeypatch, createUser) -> None:
    user = createUser(accountTier="premium")
    profile = createKoreaProfile(int(user["id"]))
    monkeypatch.setattr("CEACStatusBot.web.korea_visa_service.queryKoreaVisaStatus", lambda *args: pendingResult())

    runKoreaCaseQuery(int(profile["id"]), "korea_automatic")

    case = getKoreaCase(int(profile["id"]), int(user["id"]))
    assert case is not None
    assert case["isEnabled"] is True
    assert case["nextCheckAt"] is not None
    assert case["lastStatus"] == "审核中"

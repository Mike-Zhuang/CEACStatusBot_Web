from __future__ import annotations

from typing import Any

import pytest

from CEACStatusBot.request.query import build_ceac_url
from CEACStatusBot.web.ircc_portal_service import IRCC_API_BASE_URL, apiGet, buildIrccApiUrl
from CEACStatusBot.web.korea_visa_service import KOREA_VISA_STATUS_URL, parseKoreaVisaStatusHtml, queryKoreaVisaStatus
from CEACStatusBot.web.passport_slot_service import GTS_API_BASE_URL, fetchPassportSlotAvailability


class FakeResponse:
    def __init__(self, payload: Any, text: str = "") -> None:
        self.payload = payload
        self.text = text
        self.status_code = 200

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        return None


def test_ceac_and_ircc_guards_reject_external_hosts() -> None:
    with pytest.raises(ValueError):
        build_ceac_url("//evil.example/path")
    with pytest.raises(ValueError):
        buildIrccApiUrl("//evil.example/path")
    with pytest.raises(ValueError):
        buildIrccApiUrl("/messages?messageRefId=unsafe")


def test_korea_query_posts_to_fixed_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fakePost(url: str, **kwargs: Any) -> FakeResponse:
        captured.update({"url": url, **kwargs})
        return FakeResponse({}, "<html><body>조회된 데이터가 없습니다.</body></html>")

    monkeypatch.setattr("CEACStatusBot.web.korea_visa_service.requests.post", fakePost)
    result = queryKoreaVisaStatus("P1234567", "TEST USER", "2000-01-01")

    assert captured["url"] == KOREA_VISA_STATUS_URL
    assert captured["data"]["sBUSI_GBNO"] == "P1234567"
    assert result["status"] == "暂无查询资料"


def test_korea_parser_extracts_structured_status() -> None:
    result = parseKoreaVisaStatusHtml(
        """
        <div id="ONLINE_APPL_NO">0600000000000</div>
        <div id="APPL_DTM">2026-05-30</div>
        <div id="ENTRY_PURPOSE">观光.过境</div>
        <div id="PROC_STS_CDNM_1">审核中</div>
        """
    )

    assert result["application_no"] == "0600000000000"
    assert result["application_date"] == "2026-05-30"
    assert result["entry_purpose"] == "观光.过境"
    assert result["status"] == "审核中"


def test_gts_query_uses_fixed_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, **kwargs: Any) -> FakeResponse:
            calls.append(("POST", url, kwargs))
            return FakeResponse({"token": "token"})

        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            calls.append(("GET", url, kwargs))
            return FakeResponse({"availableDates": []})

    monkeypatch.setattr("CEACStatusBot.web.passport_slot_service.httpx.Client", FakeClient)
    fetchPassportSlotAvailability("12345678")

    assert calls[0][1] == f"{GTS_API_BASE_URL}/authenticate"
    assert calls[1][1] == f"{GTS_API_BASE_URL}/availability7days/"


def test_ircc_query_encodes_parameters_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            captured.update({"url": url, **kwargs})
            return FakeResponse([])

    monkeypatch.setattr("CEACStatusBot.web.ircc_portal_service.httpx.Client", FakeClient)
    apiGet("/messages", {"idToken": "token"}, params={"messageRefId": "//evil.example"})

    assert captured["url"] == f"{IRCC_API_BASE_URL}/messages"
    assert captured["params"]["messageRefId"] == "//evil.example"

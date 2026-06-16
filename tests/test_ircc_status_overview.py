import unittest

from CEACStatusBot.web.ircc_portal_service import (
    buildChangeSummary,
    buildIrccStatusOverview,
    formatIrccDocumentStatusItem,
    normalizeSnapshot,
    stableHash,
    summarizeSnapshot,
)


def buildSnapshot(**overrides: object) -> dict[str, object]:
    appStatus: dict[str, object] = {
        "UpdatedDate": "2026-05-28T10:00:00.000Z",
        "applicationStatus": "A11",
        "eligibility": {"status": "E2", "timeStamp": None},
        "medical": {"status": "M1", "timeStamp": None},
        "additionalDocuments": {"status": "AD1", "timeStamp": None},
        "interviewOrAppointment": {"status": "IA1", "timeStamp": None},
        "biometricInformation": {"status": "B1", "timeStamp": None},
        "backgroundChecks": {"status": "BC2", "timeStamp": None},
        "finalDecision": {"status": "FD1", "timeStamp": None},
    }
    appStatus.update(overrides)
    return {"appStatus": appStatus, "applicationInfo": {}, "messages": []}


class IrccStatusOverviewTest(unittest.TestCase):
    def test_falls_back_to_overall_status_without_stage_timestamp(self) -> None:
        overview = buildIrccStatusOverview(buildSnapshot())

        self.assertEqual(overview["headlineCode"], "A11")
        self.assertEqual(overview["tone"], "pending")
        self.assertIsNone(overview["latestUpdate"])

    def test_uses_latest_timestamped_stage_before_final_decision_exists(self) -> None:
        overview = buildIrccStatusOverview(
            buildSnapshot(biometricInformation={"status": "B3", "timeStamp": "05/22/2026 18:22:23"})
        )

        self.assertEqual(overview["headlineCode"], "B3")
        self.assertEqual(overview["latestUpdate"]["field"], "biometricInformation")

    def test_substantive_final_decision_becomes_headline(self) -> None:
        overview = buildIrccStatusOverview(buildSnapshot(finalDecision={"status": "FD6", "timeStamp": "05/28/2026"}))

        self.assertEqual(overview["headlineCode"], "FD6")
        self.assertEqual(overview["headlineText"], "已获批，需要提交护照")
        self.assertEqual(overview["tone"], "approved")
        self.assertEqual(overview["latestUpdate"]["field"], "finalDecision")
        self.assertEqual(overview["latestUpdate"]["timeStamp"], "05/28/2026")

    def test_later_workflow_stage_wins_when_timestamps_match(self) -> None:
        overview = buildIrccStatusOverview(
            buildSnapshot(
                biometricInformation={"status": "B3", "timeStamp": "05/28/2026"},
                finalDecision={"status": "FD23", "timeStamp": "05/28/2026"},
            )
        )

        self.assertEqual(overview["latestUpdate"]["field"], "finalDecision")
        self.assertEqual(overview["headlineCode"], "FD23")

    def test_unknown_code_is_preserved(self) -> None:
        overview = buildIrccStatusOverview(buildSnapshot(finalDecision={"status": "FD999", "timeStamp": "05/28/2026"}))

        self.assertEqual(overview["headlineCode"], "FD999")
        self.assertEqual(overview["headlineText"], "未知状态码：FD999")
        self.assertEqual(overview["tone"], "unknown")

    def test_detail_updated_date_does_not_affect_snapshot_hash(self) -> None:
        previous = buildSnapshot()
        current = buildSnapshot()
        current["appStatus"]["UpdatedDate"] = "2026-05-29T11:00:00.000Z"

        self.assertEqual(stableHash(normalizeSnapshot(previous)), stableHash(normalizeSnapshot(current)))

    def test_document_status_item_is_structured_and_masked(self) -> None:
        item = {
            "name": "TEST APPLICANT",
            "documentType": "DSDT01",
            "documentNumber": "D123456789",
            "documentStatus": "DS1",
            "expiryDate": "02/16/2035",
            "statusUpdatedDate": "06/16/2026",
            "travelDocumentNumber": "P987654321",
            "countryOfIssue": "202",
            "showNAExpiryDate": "N",
        }

        formatted = formatIrccDocumentStatusItem(item)

        self.assertIn("未知文件类型：DSDT01", formatted)
        self.assertIn("未知文件状态：DS1", formatted)
        self.assertIn("未知签发国家/地区代码：202", formatted)
        self.assertIn("******6789", formatted)
        self.assertIn("******4321", formatted)
        self.assertNotIn("D123456789", formatted)
        self.assertNotIn("P987654321", formatted)

    def test_document_status_change_summary_does_not_emit_raw_json(self) -> None:
        previous = buildSnapshot(documentStatus=[])
        current = buildSnapshot(
            documentStatus=[
                {
                    "name": "TEST APPLICANT",
                    "documentType": "DSDT01",
                    "documentNumber": "D123456789",
                    "documentStatus": "DS1",
                    "expiryDate": "02/16/2035",
                    "statusUpdatedDate": "06/16/2026",
                    "travelDocumentNumber": "P987654321",
                    "countryOfIssue": "202",
                    "showNAExpiryDate": "N",
                }
            ]
        )

        summary = buildChangeSummary(previous, current)

        self.assertIn("新增文件状态", summary)
        self.assertIn("未知文件状态：DS1", summary)
        self.assertNotIn("[{", summary)
        self.assertNotIn("D123456789", summary)
        self.assertNotIn("P987654321", summary)

    def test_snapshot_summary_includes_document_status_details(self) -> None:
        snapshot = buildSnapshot(
            documentStatus=[
                {
                    "documentType": "DSDT01",
                    "documentNumber": "D123456789",
                    "documentStatus": "DS1",
                    "statusUpdatedDate": "06/16/2026",
                }
            ]
        )

        summary = summarizeSnapshot(snapshot)

        self.assertIn("文件状态数量：1", summary)
        self.assertIn("文件状态：", summary)
        self.assertIn("未知文件类型：DSDT01", summary)
        self.assertNotIn("D123456789", summary)


if __name__ == "__main__":
    unittest.main()

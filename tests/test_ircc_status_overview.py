import unittest

from CEACStatusBot.web.ircc_portal_service import buildIrccStatusOverview, normalizeSnapshot, stableHash


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


if __name__ == "__main__":
    unittest.main()

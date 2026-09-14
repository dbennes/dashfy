from copy import deepcopy
from datetime import date, datetime, timezone
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import skyline_aveon_source as source


class AveonSkylineTests(SimpleTestCase):
    line = '4"-DN-473605'
    other = '6"-VA-403237'

    def ros(self):
        return {
            "available": True,
            "source": {"as_of_date": "2026-09-14", "workbook": "ROS.xlsx"},
            "kpis": {"line_count": 2, "scope_spools": 8},
            "charts": {
                "dates": [{
                    "date": "2026-12-11",
                    "forecast": [{"line": self.line, "spools": 5}, {"line": self.other, "spools": 3}],
                    "lookahead": [{"line": self.line, "spools": 5, "performed_spools": 5}],
                }],
                "material_readiness": {self.line: {"valves": {"status": "pending"}}},
            },
        }

    def package(self, pk=1, line=None, finish="2026-08-03", **changes):
        line = line or self.line
        value = {
            "id": pk, "code": f"FB-{pk:03}", "document_id": pk, "project_id": 1,
            "line": line + "-STD-H", "name": line + "-STD-H_BNO-DRAWING-1",
            "drawing_number": "BNO-DRAWING-1", "p6_ref": f"P6-{pk}",
            "plan_finish": date(2099, 1, 1), "actual_finish": None,
            "source_workbook": "AVEON Schedule 1.xlsx", "latest_import_id": 4,
            "imported_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
            "stages": {"painting": {"plan_finish": finish, "pct": 100}},
        }
        value.update(changes)
        return value

    def segments(self, payload, band):
        return [segment for bucket in payload["charts"]["dates"] for segment in bucket[band]]

    def test_dates_come_from_aveon_stages_and_ros_scope_remains_complete(self):
        ros = self.ros()
        before = deepcopy(ros)
        payload = source.build_aveon_skyline(ros, [self.package(), self.package(2, self.other)])
        planned = self.segments(payload, "forecast")
        self.assertEqual(ros, before)
        self.assertTrue(payload["available"])
        self.assertEqual({row["date"] for row in planned}, {"2026-08-03"})
        self.assertEqual(sum(row["spools"] for row in planned), 8)
        self.assertEqual(payload["kpis"]["scope_spools"], 8)
        self.assertEqual(payload["kpis"]["scheduled_spools"], 8)
        self.assertEqual(payload["charts"]["material_readiness"], ros["charts"]["material_readiness"])
        self.assertEqual(json.loads(payload["charts_json"]), payload["charts"])
        self.assertEqual(payload["source"]["workbook"], "AVEON Schedule 1.xlsx")
        self.assertEqual(payload["source"]["snapshot_date"], "2026-08-21")

    def test_past_planned_dates_and_weekly_hundred_percent_are_not_actual_finishes(self):
        package = self.package()
        package["stages"]["_weekly_progress"] = {
            "schema": 1, "source": "epc1_iso_weekly", "report_date": "2026-08-21",
            "pwht_required": False, "overall_pct": "100",
        }
        payload = source.build_aveon_skyline(self.ros(), [package])
        reported = self.segments(payload, "lookahead")[0]
        self.assertEqual(reported["date_kind"], "reported_complete")
        self.assertEqual(reported["date"], "2026-08-21")
        self.assertEqual(reported["actual_finish"], "")
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)
        segment = self.segments(payload, "forecast")[0]
        self.assertEqual(segment["fabrication_progress_pct"], 100)
        self.assertEqual(segment["progress_as_of_date"], "2026-08-21")
        self.assertEqual(segment["progress_pct"], 100)
        self.assertFalse(segment["actual_date_confirmed"])

    def test_missing_package_keeps_quantity_in_explicit_unmapped_scope(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package()])
        self.assertEqual(payload["kpis"]["scheduled_spools"], 5)
        self.assertEqual(payload["kpis"]["unmapped_spools"], 3)
        self.assertEqual(payload["kpis"]["scope_spools"], 8)
        self.assertEqual(payload["charts"]["unmapped"][0]["line"], self.other)
        self.assertIn("No matching", payload["charts"]["unmapped"][0]["reason"])

    def test_no_fabrication_stage_date_does_not_fall_back_to_ros_or_summary(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(stages={})])
        self.assertFalse(payload["available"])
        self.assertEqual(payload["charts"]["dates"], [])
        self.assertEqual(payload["kpis"]["unmapped_spools"], 8)

    def test_missing_finish_on_a_scheduled_stage_does_not_hide_in_other_dates(self):
        stages = {"hydrotest": {"plan_finish": "2026-08-03"}, "painting": {"plan_finish": None, "acts": [{"id": "PAINT-1"}]}}
        payload = source.build_aveon_skyline(self.ros(), [self.package(stages=stages)])
        self.assertEqual(self.segments(payload, "forecast"), [])
        self.assertEqual(payload["kpis"]["scheduled_spools"], 0)
        self.assertEqual(self.segments(payload, "lookahead")[0]["planned_finish"], "")

    def test_unlinked_package_name_uses_explicit_identity_with_quoted_specification(self):
        ros = self.ros()
        ros["charts"]["dates"][0]["forecast"][0]["line"] = '12"-PM-043107'
        package = self.package(line="", document_id=None, project_id=None,
                               name='12"-PM-043107-"1800"-IFJ_BNO-DRAWING-1')
        package["line"] = ""
        payload = source.build_aveon_skyline(ros, [package])
        segment = self.segments(payload, "forecast")[0]
        self.assertEqual(segment["line"], '12"-PM-043107')
        self.assertEqual(segment["package_ids"], [1])

    def test_size_and_service_and_complete_line_number_prevent_cross_line_matches(self):
        for wrong in ['2"-DN-473605', '4"-DC-473605', '4"-DN-4736050']:
            with self.subTest(line=wrong):
                payload = source.build_aveon_skyline(self.ros(), [self.package(line=wrong)])
                self.assertEqual(self.segments(payload, "forecast"), [])

    def test_conflicting_document_and_package_line_is_explicitly_unmapped(self):
        package = self.package(name=self.other + "-STD-H_BNO-DRAWING-1")
        payload = source.build_aveon_skyline(self.ros(), [package])
        self.assertFalse(payload["available"])
        self.assertTrue(any("disagree" in row["reason"] for row in payload["charts"]["unmapped"]))

    def test_unique_exact_linked_drawing_resolves_wbs_name_typo_with_evidence(self):
        package = self.package(name=self.other + "-STD-H_BNO-DRAWING-1",
                               document_drawing_number="BNO-DRAWING-1", drawing_identity_unique=True)
        payload = source.build_aveon_skyline(self.ros(), [package])
        segment = self.segments(payload, "forecast")[0]
        self.assertEqual(segment["line"], self.line)
        self.assertIn("Exact linked drawing BNO-DRAWING-1", segment["line_mapping_note"])
        self.assertIn(self.other, segment["line_mapping_note"])
        self.assertEqual(segment["schedule_note"], segment["line_mapping_note"])
        self.assertEqual(payload["charts"]["unmapped"][0]["line"], self.other)
        package["drawing_identity_unique"] = False
        ambiguous = source.build_aveon_skyline(self.ros(), [package])
        self.assertEqual(self.segments(ambiguous, "forecast"), [])

    def test_unattributable_import_is_not_treated_as_aveon(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(source_workbook="ROS.xlsx")])
        self.assertEqual(self.segments(payload, "forecast"), [])
        self.assertTrue(any("attributable" in row["reason"] for row in payload["charts"]["unmapped"]))

    def test_multiple_packages_use_latest_full_finish_without_multiplying_spools(self):
        packages = [self.package(), self.package(2, finish="2026-08-20")]
        payload = source.build_aveon_skyline(self.ros(), packages)
        planned = self.segments(payload, "forecast")
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["date"], "2026-08-20")
        self.assertEqual(planned[0]["spools"], 5)
        self.assertEqual(planned[0]["fabrication_progress_pct"], 100)
        self.assertEqual(len(planned[0]["fabrication_progress"]), 2)

    def test_actual_finish_requires_every_package_and_nonfuture_dates(self):
        first = self.package(actual_finish=date(2026, 8, 4))
        second = self.package(2, actual_finish=date(2026, 9, 15))
        payload = source.build_aveon_skyline(self.ros(), [first, second])
        reported = self.segments(payload, "lookahead")[0]
        self.assertFalse(reported["actual_date_confirmed"])
        self.assertEqual(reported["actual_finish"], "")
        self.assertEqual(reported["date_kind"], "reported_complete")
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)
        second["actual_finish"] = date(2026, 8, 6)
        payload = source.build_aveon_skyline(self.ros(), [first, second])
        actual = self.segments(payload, "lookahead")[0]
        self.assertEqual(actual["date"], "2026-08-06")
        self.assertEqual(actual["status"], "late")
        self.assertEqual(actual["spools"], 5)
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 5)
        self.assertEqual(payload["kpis"]["remaining_spools"], 3)

    def test_multiple_projects_are_not_merged(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(), self.package(2, project_id=2)])
        self.assertEqual(self.segments(payload, "forecast"), [])
        self.assertTrue(any("multiple DATAFY projects" in row["reason"] for row in payload["charts"]["unmapped"]))

    def test_later_painting_finish_is_part_of_full_fabrication(self):
        stages = {"hydrotest": {"plan_finish": "2026-08-10"}, "painting": {"plan_finish": "2026-08-19"}}
        payload = source.build_aveon_skyline(self.ros(), [self.package(stages=stages)])
        self.assertEqual(self.segments(payload, "forecast")[0]["date"], "2026-08-19")

    def test_source_failure_never_returns_ros_dates_as_aveon(self):
        with patch.object(source, "aveon_skyline", side_effect=RuntimeError("offline")), patch.object(source.logger, "exception"):
            payload = source.aveon_skyline_safe(self.ros())
        self.assertFalse(payload["available"])
        self.assertEqual(payload["charts"]["dates"], [])
        self.assertEqual(payload["kpis"]["scope_spools"], 8)
        self.assertEqual(payload["kpis"]["unmapped_spools"], 8)

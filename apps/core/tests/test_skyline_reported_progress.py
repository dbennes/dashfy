from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.core import skyline_aveon_source as source


class SkylineReportedProgressTests(SimpleTestCase):
    line = '4"-DN-473605'

    def ros(self):
        return {
            "available": True,
            "source": {"as_of_date": "2026-09-14", "workbook": "ROS.xlsx"},
            "kpis": {"line_count": 1, "scope_spools": 5},
            "charts": {
                "dates": [{
                    "date": "2026-12-11",
                    "forecast": [{"line": self.line, "spools": 5}],
                    "lookahead": [{
                        "line": self.line, "spools": 5, "performed_spools": 5,
                        "progress_pct": 100, "status": "on_time",
                    }],
                }],
                "material_readiness": {},
            },
        }

    def package(self, pk=1, *, pct="33.7103783827178", reported="2026-09-11",
                planned="2026-09-10", weekly_source="epc1_pms_weekly", **changes):
        marker = {
            "schema": 1, "source": weekly_source, "report_date": reported,
            "overall_pct": pct,
        }
        if weekly_source == "epc1_pms_weekly":
            marker.update(mode="overall_only", pwht_required=None,
                          stage_pwht_required=False, stage_report_date="2026-08-21")
        else:
            marker["pwht_required"] = False
        package = {
            "id": pk, "code": f"FB-{pk:03}", "document_id": pk, "project_id": 1,
            "line": self.line + "-STD-H",
            "name": self.line + f"-STD-H_BNO-DRAWING-{pk}",
            "drawing_number": f"BNO-DRAWING-{pk}", "p6_ref": f"P6-{pk}",
            "plan_finish": date(2099, 1, 1), "actual_finish": None,
            "source_workbook": "AVEON Schedule 1.xlsx", "latest_import_id": 4,
            "imported_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
            "stages": {
                "painting": {"plan_finish": planned, "pct": 100},
                "_weekly_progress": marker,
            },
        }
        package.update(changes)
        return package

    def entry(self, pk, day, pct, *, package_id=1, overall_after=None):
        return {
            "id": pk, "package_id": package_id, "progress_date": day,
            "stages": {"_overall_pct": str(pct)},
            "overall_after": str(pct) if overall_after is None else overall_after,
        }

    def segments(self, payload, band="lookahead"):
        return [segment for bucket in payload["charts"]["dates"] for segment in bucket[band]]

    def lower(self, payload):
        segments = self.segments(payload)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["line"], self.line)
        self.assertEqual(segments[0]["spools"], 5)
        planned = segments[0]["planned_finish"]
        for band in ("forecast", "lookahead"):
            rows = self.segments(payload, band)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["date"], planned)
            self.assertEqual(rows[0]["dates"], [planned])
            self.assertEqual(rows[0]["date_kind"], "planned")
        self.assertEqual(
            [bucket["date"] for bucket in payload["charts"]["dates"] if bucket["forecast"]],
            [bucket["date"] for bucket in payload["charts"]["dates"] if bucket["lookahead"]],
        )
        return segments[0]

    def unmapped(self, payload):
        self.assertFalse(payload["available"])
        self.assertEqual(payload["charts"]["dates"], [])
        self.assertEqual(len(payload["charts"]["unmapped"]), 1)
        row = payload["charts"]["unmapped"][0]
        self.assertEqual(row["line"], self.line)
        self.assertEqual(row["spools"], 5)
        self.assertTrue(row["reason"])
        return row

    def test_pms_overall_overrides_older_completed_stage_values(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package()])
        lower = self.lower(payload)
        self.assertEqual(lower["status"], "partial")
        self.assertEqual(lower["progress_date_kind"], "progress")
        self.assertEqual(lower["date"], "2026-09-10")
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")
        self.assertEqual(lower["progress_pct"], 33.7103783827178)
        self.assertEqual(lower["fabrication_progress_pct"], 33.7103783827178)
        self.assertFalse(lower["actual_date_confirmed"])
        self.assertFalse(lower["actual_finish"])
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)

    def test_iso_weekly_percent_uses_same_lower_band_contract(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="17.16531969256482", weekly_source="epc1_iso_weekly")],
        )
        lower = self.lower(payload)
        self.assertEqual(lower["status"], "partial")
        self.assertEqual(lower["progress_pct"], 17.16531969256482)
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")

    def test_partial_progress_keeps_integer_scope_in_both_bands(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(pct="25")])
        self.assertEqual(self.lower(payload)["spools"], 5)
        for band in ("forecast", "lookahead"):
            segments = self.segments(payload, band)
            self.assertEqual(sum(row["spools"] for row in segments), 5)
            self.assertTrue(all(isinstance(row["spools"], int) for row in segments))
        self.assertEqual(payload["kpis"]["scope_spools"], 5)
        self.assertEqual(payload["kpis"]["scheduled_spools"], 5)

    def test_zero_progress_stays_upcoming_at_aveon_planned_date(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(pct="0")])
        lower = self.lower(payload)
        self.assertEqual(lower["status"], "upcoming")
        self.assertEqual(lower["progress_date_kind"], "progress")
        self.assertEqual(lower["date"], "2026-09-10")
        self.assertEqual(lower["progress_pct"], 0)
        self.assertFalse(lower["actual_date_confirmed"])

    def test_reported_completion_preserves_report_date_without_fabricating_actual_finish(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(pct="100")])
        lower = self.lower(payload)
        self.assertEqual(lower["status"], "late")
        self.assertEqual(lower["progress_date_kind"], "reported_complete")
        self.assertEqual(lower["reported_completion_date"], "2026-09-11")
        self.assertEqual(lower["progress_pct"], 100)
        self.assertFalse(lower["actual_date_confirmed"])
        self.assertFalse(lower["actual_finish"])
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)

    def test_reported_completion_colors_compare_completion_date_to_aveon_plan(self):
        for planned, expected in (("2026-09-10", "late"), ("2026-09-11", "on_time"),
                                  ("2026-09-14", "on_time")):
            with self.subTest(planned=planned):
                payload = source.build_aveon_skyline(
                    self.ros(), [self.package(pct="100", planned=planned)],
                )
                self.assertEqual(self.lower(payload)["status"], expected)

    def test_first_complete_observation_is_preserved_by_later_hundred_percent_reports(self):
        history = [
            self.entry(3, "2026-09-11", "100"),
            self.entry(1, "2026-08-28", "75"),
            self.entry(2, "2026-09-04", "100"),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100")], progress_entries=history,
        )
        lower = self.lower(payload)
        self.assertEqual(lower["reported_completion_date"], "2026-09-04")
        self.assertEqual(lower["status"], "on_time")
        self.assertEqual(lower["progress_date_kind"], "reported_complete")
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")
        self.assertIsInstance(lower["progress_history"], list)
        self.assertTrue(lower["progress_history"])

    def test_completion_date_restarts_after_a_reported_regression(self):
        history = [
            self.entry(1, "2026-08-21", "100"),
            self.entry(2, "2026-08-28", "80"),
            self.entry(3, "2026-09-04", "95"),
            self.entry(4, "2026-09-11", "100"),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100")], progress_entries=history,
        )
        self.assertEqual(self.lower(payload)["reported_completion_date"], "2026-09-11")
        self.assertEqual(self.lower(payload)["status"], "late")

    def test_current_partial_report_does_not_reuse_an_old_completion(self):
        history = [self.entry(1, "2026-09-04", "100"), self.entry(2, "2026-09-11", "40")]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="40")], progress_entries=history,
        )
        lower = self.lower(payload)
        self.assertEqual(lower["status"], "partial")
        self.assertEqual(lower["progress_date_kind"], "progress")
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")
        self.assertEqual(lower["progress_pct"], 40)

    def test_history_uses_exact_reported_percentage_before_rounded_overall_after(self):
        history = [self.entry(1, "2026-09-04", "99.99", overall_after="100")]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100")], progress_entries=history,
        )
        self.assertEqual(self.lower(payload)["reported_completion_date"], "2026-09-11")
        self.assertEqual(self.lower(payload)["status"], "late")

    def test_future_weekly_marker_falls_back_to_latest_nonfuture_report(self):
        history = [
            self.entry(1, "2026-09-11", "40"),
            self.entry(2, "2026-09-18", "100"),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", reported="2026-09-18")],
            progress_entries=history,
        )
        lower = self.lower(payload)
        self.assertEqual(lower["progress_pct"], 40)
        self.assertEqual(lower["status"], "partial")
        self.assertEqual(lower["date"], "2026-09-10")
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")
        self.assertFalse(lower["actual_finish"])

    def test_future_report_is_never_used_as_past_completion_evidence(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", reported="2026-09-18")],
        )
        lower = self.lower(payload)
        self.assertNotEqual(lower["progress_as_of_date"], "2026-09-18")
        self.assertNotEqual(lower["progress_date_kind"], "reported_complete")
        self.assertFalse(lower["actual_date_confirmed"])
        self.assertFalse(lower["actual_finish"])

    def test_multiple_packages_use_arithmetic_mean_and_one_full_scope_box(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100"), self.package(2, pct="20")],
        )
        lower = self.lower(payload)
        self.assertEqual(lower["progress_pct"], 60)
        self.assertEqual(lower["fabrication_progress_pct"], 60)
        self.assertEqual(lower["status"], "partial")
        self.assertEqual(lower["spools"], 5)
        self.assertEqual(len(self.segments(payload, "forecast")), 1)
        self.assertEqual(payload["kpis"]["scope_spools"], 5)
        self.assertEqual(set(lower["package_ids"]), {1, 2})

    def test_multiple_packages_complete_when_last_package_reaches_hundred_percent(self):
        history = [
            self.entry(1, "2026-09-04", "100", package_id=1),
            self.entry(2, "2026-09-04", "70", package_id=2),
            self.entry(3, "2026-09-11", "100", package_id=1),
            self.entry(4, "2026-09-11", "100", package_id=2),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100"), self.package(2, pct="100")],
            progress_entries=history,
        )
        lower = self.lower(payload)
        self.assertEqual(lower["progress_pct"], 100)
        self.assertEqual(lower["status"], "late")
        self.assertEqual(lower["reported_completion_date"], "2026-09-11")
        self.assertEqual(lower["progress_date_kind"], "reported_complete")
        self.assertFalse(lower["actual_date_confirmed"])

    def test_completion_tolerance_does_not_round_99_point_99_up_to_complete(self):
        for pct, status, date_kind in (
            ("99.99999999999999", "late", "reported_complete"),
            ("99.99", "partial", "progress"),
        ):
            with self.subTest(pct=pct):
                payload = source.build_aveon_skyline(self.ros(), [self.package(pct=pct)])
                lower = self.lower(payload)
                self.assertEqual(lower["status"], status)
                self.assertEqual(lower["progress_date_kind"], date_kind)

    def test_explicit_nonfuture_actual_finish_retains_its_confirmed_date(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", actual_finish=date(2026, 9, 3))],
        )
        lower = self.lower(payload)
        self.assertEqual(lower["progress_date_kind"], "actual")
        self.assertEqual(lower["date"], "2026-09-10")
        self.assertEqual(lower["status"], "on_time")
        self.assertTrue(lower["actual_date_confirmed"])
        self.assertEqual(lower["actual_finish"], "2026-09-03")
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 5)

    def test_missing_report_metadata_never_borrows_ros_dates_or_completion(self):
        package = self.package()
        package["stages"].pop("_weekly_progress")
        package["stages"]["painting"]["pct"] = 0
        package["imported_at"] = None
        payload = source.build_aveon_skyline(self.ros(), [package])
        lower = self.lower(payload)
        self.assertEqual(lower["date"], "2026-09-10")
        self.assertEqual(lower["progress_date_kind"], "planned")
        self.assertEqual(lower["status"], "upcoming")
        self.assertFalse(lower["actual_date_confirmed"])
        self.assertFalse(lower["actual_finish"])
        self.assertNotIn("2026-12-11", [row["date"] for row in self.segments(payload, "forecast")])

    def test_input_payload_packages_and_history_are_not_mutated(self):
        ros = self.ros()
        packages = [self.package(pct="100")]
        history = [self.entry(1, "2026-09-04", "100")]
        originals = deepcopy((ros, packages, history))
        source.build_aveon_skyline(ros, packages, progress_entries=history)
        self.assertEqual((ros, packages, history), originals)

    def test_source_reads_history_through_postgres_adapter_with_bound_cutoff(self):
        package_cursor = Mock()
        package_cursor.fetchall.return_value = [self.package(pct="100")]
        history_cursor = Mock()
        history_cursor.fetchall.return_value = [
            self.entry(1, "2026-09-04", "100"),
            self.entry(2, "2026-09-11", "100"),
        ]
        driver = Mock()
        driver.cursor.side_effect = [package_cursor, history_cursor]
        connection = source.real_sources._PostgresCompatConnection(driver)
        with patch.object(source.real_sources, "_datafy_conn", return_value=nullcontext(connection)):
            payload = source.aveon_skyline(self.ros())

        self.assertEqual(driver.cursor.call_count, 2)
        package_cursor.execute.assert_called_once()
        package_query, package_params = package_cursor.execute.call_args.args
        self.assertIn("fabrication_fabricationpackage", package_query)
        self.assertEqual(package_params, ())
        history_cursor.execute.assert_called_once()
        history_query, history_params = history_cursor.execute.call_args.args
        self.assertIn("fabrication_fabricationprogressentry", history_query)
        self.assertIn("e.progress_date <= %s", history_query)
        self.assertNotIn("%%s", history_query)
        self.assertEqual(history_params, (date(2026, 9, 14),))
        lower = self.lower(payload)
        self.assertEqual(lower["reported_completion_date"], "2026-09-04")
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")
        self.assertEqual(lower["progress_date_kind"], "reported_complete")
        self.assertEqual(lower["status"], "on_time")

    def test_partial_report_without_plan_is_kept_in_unmapped_evidence(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(planned=None, pct="25")],
        )
        evidence = self.unmapped(payload)
        self.assertEqual(evidence["progress_as_of_date"], "2026-09-11")
        self.assertEqual(evidence["fabrication_progress_pct"], 25)
        self.assertFalse(evidence["actual_finish"])
        self.assertFalse(evidence["reported_completion_date"])

    def test_completed_report_without_plan_preserves_completion_as_unmapped_evidence(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(planned=None, pct="100")],
        )
        evidence = self.unmapped(payload)
        self.assertEqual(evidence["progress_as_of_date"], "2026-09-11")
        self.assertEqual(evidence["fabrication_progress_pct"], 100)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-11")
        self.assertFalse(evidence["actual_finish"])

    def test_zero_report_without_planned_finish_is_kept_in_unmapped_evidence(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(planned=None, pct="0")],
        )
        evidence = self.unmapped(payload)
        self.assertEqual(evidence["progress_as_of_date"], "2026-09-11")
        self.assertEqual(evidence["fabrication_progress_pct"], 0)
        self.assertFalse(evidence["actual_finish"])
        self.assertFalse(evidence["reported_completion_date"])

    def test_newer_partial_report_supersedes_an_older_explicit_actual_finish(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="40", actual_finish=date(2026, 9, 3))],
        )
        lower = self.lower(payload)
        self.assertEqual(lower["progress_as_of_date"], "2026-09-11")
        self.assertEqual(lower["progress_pct"], 40)
        self.assertEqual(lower["status"], "partial")
        self.assertEqual(lower["progress_date_kind"], "progress")
        self.assertFalse(lower["actual_date_confirmed"])
        self.assertFalse(lower["actual_finish"])
        self.assertEqual(lower["performed_spools"], 0)
        self.assertEqual(lower["source_actual_finish"], "2026-09-03")
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)

    def test_recompletion_after_regression_does_not_revive_superseded_actual_date(self):
        history = [
            self.entry(1, "2026-09-03", "100"),
            self.entry(2, "2026-09-04", "40"),
            self.entry(3, "2026-09-11", "100"),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", actual_finish=date(2026, 9, 3))],
            progress_entries=history,
        )
        lower = self.lower(payload)
        self.assertEqual(lower["reported_completion_date"], "2026-09-11")
        self.assertEqual(lower["progress_date_kind"], "reported_complete")
        self.assertEqual(lower["status"], "late")
        self.assertFalse(lower["actual_date_confirmed"])
        self.assertFalse(lower["actual_finish"])
        self.assertEqual(lower["source_actual_finish"], "2026-09-03")

    def test_weekly_progress_updates_preserve_planned_column_and_weekly_scope_totals(self):
        before = source.build_aveon_skyline(
            self.ros(), [self.package(pct="25", reported="2026-09-04", planned="2026-10-01")],
        )
        after = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", reported="2026-09-11", planned="2026-10-01")],
            progress_entries=[
                self.entry(1, "2026-09-04", "25"),
                self.entry(2, "2026-09-11", "100"),
            ],
        )
        first = self.lower(before)
        latest = self.lower(after)
        self.assertEqual(first["date"], "2026-10-01")
        self.assertEqual(latest["date"], first["date"])
        self.assertEqual(first["progress_pct"], 25)
        self.assertEqual(latest["progress_pct"], 100)
        self.assertEqual(first["status"], "partial")
        self.assertEqual(latest["status"], "on_time")
        self.assertEqual(first["progress_as_of_date"], "2026-09-04")
        self.assertEqual(latest["progress_as_of_date"], "2026-09-11")
        self.assertEqual(latest["reported_completion_date"], "2026-09-11")
        for payload in (before, after):
            self.assertEqual([
                (bucket["date"], bucket["forecast_total"], bucket["lookahead_total"])
                for bucket in payload["charts"]["dates"]
            ], [("2026-10-02", 5, 5)])

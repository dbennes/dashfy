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

    def forecast(self, payload):
        rows = self.segments(payload, "forecast")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], self.line)
        self.assertEqual(rows[0]["spools"], 5)
        self.assertEqual(rows[0]["date"], rows[0]["planned_finish"])
        self.assertEqual(rows[0]["dates"], [rows[0]["planned_finish"]])
        self.assertEqual(rows[0]["date_kind"], "planned")
        return rows[0]

    def actual(self, payload):
        rows = self.segments(payload)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["line"], self.line)
        self.assertEqual(row["spools"], 5)
        self.assertTrue(row["actual_date_confirmed"])
        self.assertEqual(row["date"], row["actual_finish"])
        self.assertEqual(row["dates"], [row["actual_finish"]])
        self.assertEqual(row["date_kind"], "actual")
        return row

    def undated(self, payload):
        self.assertEqual(self.segments(payload), [])
        rows = payload["charts"]["undated_completions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], self.line)
        self.assertEqual(rows[0]["spools"], 5)
        self.assertFalse(rows[0]["actual_finish"])
        self.assertEqual(payload["kpis"]["undated_completed_lines"], 1)
        self.assertEqual(payload["kpis"]["undated_completed_spools"], 5)
        self.assertEqual(payload["kpis"]["performed_line_count"], 0)
        self.assertEqual(payload["kpis"]["performed_spools"], 0)
        return rows[0]

    def no_completion(self, payload):
        self.assertEqual(self.segments(payload), [])
        self.assertEqual(payload["charts"]["undated_completions"], [])
        self.assertEqual(payload["kpis"]["performed_spools"], 0)
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)
        self.assertEqual(payload["kpis"]["undated_completed_spools"], 0)

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
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_as_of_date"], "2026-09-11")
        self.assertEqual(forecast["progress_pct"], 33.7103783827178)
        self.assertEqual(forecast["fabrication_progress_pct"], 33.7103783827178)
        self.assertFalse(forecast["actual_date_confirmed"])
        self.assertFalse(forecast["actual_finish"])
        self.no_completion(payload)

    def test_iso_weekly_percent_remains_exact_in_forecast_evidence(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="17.16531969256482", weekly_source="epc1_iso_weekly")],
        )
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_pct"], 17.16531969256482)
        self.assertEqual(forecast["progress_as_of_date"], "2026-09-11")
        self.no_completion(payload)

    def test_partial_progress_keeps_full_scope_in_forecast_without_actual_spools(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(pct="25")])
        forecast = self.forecast(payload)
        self.assertEqual(forecast["spools"], 5)
        self.assertIsInstance(forecast["spools"], int)
        self.assertEqual(payload["kpis"]["scope_spools"], 5)
        self.assertEqual(payload["kpis"]["scheduled_spools"], 5)
        self.no_completion(payload)
        self.assertEqual(payload["charts"]["status_totals"]["partial"], 0)

    def test_zero_progress_does_not_create_a_lower_box(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(pct="0")])
        forecast = self.forecast(payload)
        self.assertEqual(forecast["date"], "2026-09-10")
        self.assertEqual(forecast["progress_pct"], 0)
        self.no_completion(payload)
        self.assertEqual(payload["charts"]["status_totals"]["upcoming"], 0)

    def test_reported_hundred_percent_is_undated_without_an_actual_finish(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(pct="100")])
        evidence = self.undated(payload)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-11")
        self.assertEqual(evidence["fabrication_progress_pct"], 100)
        self.assertEqual(self.forecast(payload)["progress_pct"], 100)
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 0)

    def test_reported_completion_never_classifies_actual_as_on_time_or_late(self):
        for planned in ("2026-09-10", "2026-09-11", "2026-09-14"):
            with self.subTest(planned=planned):
                payload = source.build_aveon_skyline(
                    self.ros(), [self.package(pct="100", planned=planned)],
                )
                self.undated(payload)
                self.assertEqual(payload["charts"]["status_totals"]["on_time"], 0)
                self.assertEqual(payload["charts"]["status_totals"]["late"], 0)

    def test_first_reported_completion_is_preserved_in_undated_history(self):
        history = [
            self.entry(3, "2026-09-11", "100"),
            self.entry(1, "2026-08-28", "75"),
            self.entry(2, "2026-09-04", "100"),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100")], progress_entries=history,
        )
        evidence = self.undated(payload)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-04")
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_as_of_date"], "2026-09-11")
        self.assertIsInstance(forecast["progress_history"], list)
        self.assertTrue(forecast["progress_history"])

    def test_reported_completion_date_restarts_after_a_regression(self):
        history = [
            self.entry(1, "2026-08-21", "100"),
            self.entry(2, "2026-08-28", "80"),
            self.entry(3, "2026-09-04", "95"),
            self.entry(4, "2026-09-11", "100"),
        ]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100")], progress_entries=history,
        )
        self.assertEqual(self.undated(payload)["reported_completion_date"], "2026-09-11")

    def test_current_partial_report_does_not_reuse_an_old_completion(self):
        history = [self.entry(1, "2026-09-04", "100"), self.entry(2, "2026-09-11", "40")]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="40")], progress_entries=history,
        )
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_as_of_date"], "2026-09-11")
        self.assertEqual(forecast["progress_pct"], 40)
        self.assertFalse(forecast["reported_completion_date"])
        self.no_completion(payload)

    def test_history_uses_exact_percentage_before_rounded_overall_after(self):
        history = [self.entry(1, "2026-09-04", "99.99", overall_after="100")]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100")], progress_entries=history,
        )
        self.assertEqual(self.undated(payload)["reported_completion_date"], "2026-09-11")

    def test_future_weekly_marker_falls_back_to_latest_nonfuture_report(self):
        history = [self.entry(1, "2026-09-11", "40"), self.entry(2, "2026-09-18", "100")]
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", reported="2026-09-18")],
            progress_entries=history,
        )
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_pct"], 40)
        self.assertEqual(forecast["progress_as_of_date"], "2026-09-11")
        self.assertFalse(forecast["actual_finish"])
        self.no_completion(payload)

    def test_future_report_is_never_used_as_past_completion_evidence(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", reported="2026-09-18")],
        )
        forecast = self.forecast(payload)
        self.assertNotEqual(forecast["progress_as_of_date"], "2026-09-18")
        self.assertFalse(forecast["reported_completion_date"])
        self.no_completion(payload)

    def test_multiple_packages_use_arithmetic_mean_without_duplicating_scope(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100"), self.package(2, pct="20")],
        )
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_pct"], 60)
        self.assertEqual(forecast["fabrication_progress_pct"], 60)
        self.assertEqual(payload["kpis"]["scope_spools"], 5)
        self.assertEqual(set(forecast["package_ids"]), {1, 2})
        self.no_completion(payload)

    def test_all_packages_reported_complete_produce_one_undated_line(self):
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
        evidence = self.undated(payload)
        self.assertEqual(evidence["fabrication_progress_pct"], 100)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-11")
        self.assertEqual(self.forecast(payload)["spools"], 5)

    def test_completion_tolerance_does_not_round_99_point_99_up_to_complete(self):
        for pct, undated_lines in (("99.99999999999999", 1), ("99.99", 0)):
            with self.subTest(pct=pct):
                payload = source.build_aveon_skyline(self.ros(), [self.package(pct=pct)])
                self.assertEqual(self.segments(payload), [])
                self.assertEqual(len(payload["charts"]["undated_completions"]), undated_lines)
                self.assertEqual(payload["kpis"]["undated_completed_lines"], undated_lines)
                self.assertEqual(payload["kpis"]["performed_spools"], 0)

    def test_explicit_nonfuture_actual_finish_uses_actual_date_in_lower_band(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", actual_finish=date(2026, 9, 3))],
        )
        actual = self.actual(payload)
        self.assertEqual(actual["date"], "2026-09-03")
        self.assertEqual(actual["status"], "on_time")
        self.assertEqual(self.forecast(payload)["date"], "2026-09-10")
        self.assertEqual(payload["kpis"]["performed_line_count"], 1)
        self.assertEqual(payload["kpis"]["performed_spools"], 5)
        self.assertEqual(payload["kpis"]["confirmed_actual_spools"], 5)
        self.assertEqual(payload["charts"]["undated_completions"], [])

    def test_actual_completion_colors_compare_real_finish_to_planned_finish(self):
        for planned, expected in (("2026-09-02", "late"), ("2026-09-03", "on_time"),
                                  ("2026-09-10", "on_time")):
            with self.subTest(planned=planned):
                payload = source.build_aveon_skyline(
                    self.ros(), [self.package(pct="100", planned=planned,
                                             actual_finish=date(2026, 9, 3))],
                )
                actual = self.actual(payload)
                self.assertEqual(actual["date"], "2026-09-03")
                self.assertEqual(actual["status"], expected)
                self.assertEqual(actual["progress_as_of_date"], "2026-09-11")

    def test_missing_report_metadata_never_borrows_ros_completion(self):
        package = self.package()
        package["stages"].pop("_weekly_progress")
        package["stages"]["painting"]["pct"] = 0
        package["imported_at"] = None
        payload = source.build_aveon_skyline(self.ros(), [package])
        forecast = self.forecast(payload)
        self.assertEqual(forecast["date"], "2026-09-10")
        self.assertFalse(forecast["actual_date_confirmed"])
        self.assertFalse(forecast["actual_finish"])
        self.no_completion(payload)

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
            self.entry(1, "2026-09-04", "100"), self.entry(2, "2026-09-11", "100"),
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
        evidence = self.undated(payload)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-04")
        self.assertEqual(self.forecast(payload)["progress_as_of_date"], "2026-09-11")

    def test_partial_report_without_plan_is_kept_in_unmapped_evidence(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(planned=None, pct="25")])
        evidence = self.unmapped(payload)
        self.assertEqual(evidence["progress_as_of_date"], "2026-09-11")
        self.assertEqual(evidence["fabrication_progress_pct"], 25)
        self.no_completion(payload)

    def test_reported_completion_without_plan_stays_undated(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(planned=None, pct="100")])
        evidence = self.undated(payload)
        self.assertEqual(self.segments(payload, "forecast"), [])
        self.assertEqual(evidence["fabrication_progress_pct"], 100)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-11")

    def test_confirmed_actual_without_plan_still_plots_at_real_completion_date(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(planned=None, pct="100", actual_finish=date(2026, 9, 3))],
        )
        actual = self.actual(payload)
        self.assertTrue(payload["available"])
        self.assertEqual(self.segments(payload, "forecast"), [])
        self.assertEqual(actual["date"], "2026-09-03")
        self.assertEqual(actual["status"], "completed")
        self.assertFalse(actual["planned_finish"])
        self.assertEqual(payload["kpis"]["completed_line_count"], 1)
        self.assertEqual(payload["kpis"]["performed_spools"], 5)
        self.assertEqual(payload["kpis"]["undated_completed_spools"], 0)

    def test_zero_report_without_planned_finish_is_kept_in_unmapped_evidence(self):
        payload = source.build_aveon_skyline(self.ros(), [self.package(planned=None, pct="0")])
        evidence = self.unmapped(payload)
        self.assertEqual(evidence["progress_as_of_date"], "2026-09-11")
        self.assertEqual(evidence["fabrication_progress_pct"], 0)
        self.no_completion(payload)

    def test_newer_partial_report_supersedes_an_older_explicit_actual_finish(self):
        payload = source.build_aveon_skyline(
            self.ros(), [self.package(pct="40", actual_finish=date(2026, 9, 3))],
        )
        forecast = self.forecast(payload)
        self.assertEqual(forecast["progress_pct"], 40)
        self.assertFalse(forecast["actual_date_confirmed"])
        self.assertFalse(forecast["actual_finish"])
        self.assertEqual(forecast["source_actual_finish"], "2026-09-03")
        self.no_completion(payload)

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
        evidence = self.undated(payload)
        self.assertEqual(evidence["reported_completion_date"], "2026-09-11")
        self.assertEqual(evidence["source_actual_finish"], "2026-09-03")

    def test_weekly_reports_do_not_invent_actual_boxes_or_move_forecast_scope(self):
        before = source.build_aveon_skyline(
            self.ros(), [self.package(pct="25", reported="2026-09-04", planned="2026-10-01")],
        )
        after = source.build_aveon_skyline(
            self.ros(), [self.package(pct="100", reported="2026-09-11", planned="2026-10-01")],
            progress_entries=[self.entry(1, "2026-09-04", "25"), self.entry(2, "2026-09-11", "100")],
        )
        first = self.forecast(before)
        latest = self.forecast(after)
        self.assertEqual(first["date"], "2026-10-01")
        self.assertEqual(latest["date"], first["date"])
        self.assertEqual(first["progress_pct"], 25)
        self.assertEqual(latest["progress_pct"], 100)
        self.assertEqual(first["progress_as_of_date"], "2026-09-04")
        self.assertEqual(latest["progress_as_of_date"], "2026-09-11")
        self.no_completion(before)
        self.assertEqual(self.undated(after)["reported_completion_date"], "2026-09-11")
        for payload in (before, after):
            self.assertEqual([
                (bucket["date"], bucket["forecast_total"], bucket["lookahead_total"])
                for bucket in payload["charts"]["dates"]
            ], [("2026-10-02", 5, 0)])

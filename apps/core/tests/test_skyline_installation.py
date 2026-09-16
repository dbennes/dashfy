from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.rundown_discipline_source import installation_rundown_sample
from apps.core.skyline_installation_source import installation_skyline_sample
from apps.core.skyline_source import fabrication_skyline


def segments(payload, band):
    return [row for bucket in payload["charts"]["dates"] for row in bucket[band]]


class InstallationSkylineSampleTests(SimpleTestCase):
    scope = {
        '1.1/2"-DN-473601': 1, '2"-DN-473602': 2, '4"-DN-473603': 7,
        '6"-DN-473604': 11, '8"-DN-473605': 3, '10"-DN-473606': 4,
        '12"-DN-473607': 6, '14"-DN-473608': 8, '16"-DN-473609': 5,
        '18"-DN-473610': 9, '20"-DN-473611': 2, '24"-DN-473612': 13,
    }

    def ros(self):
        rows = [{
            "line": line, "spools": quantity, "date": "2099-12-04",
            "dates": ["2099-12-04"], "status": "on_time",
            "performed_spools": quantity, "actual_finish": "2099-12-03",
        } for line, quantity in self.scope.items()]
        return {
            "available": True,
            "source": {
                "workbook": "ROS scope.xlsx", "snapshot_date": "2026-09-03",
                "snapshot_label": "03 Sep 26", "as_of_date": "2099-12-31",
            },
            # Quantities must come from segments, even if cached KPIs are stale.
            "kpis": {"line_count": 999, "scope_spools": 9999},
            "charts": {
                "dates": [
                    {"date": "2099-12-04", "forecast": rows[:6], "lookahead": []},
                    {"date": "2099-12-11", "forecast": rows[6:], "lookahead": deepcopy(rows)},
                ],
                "material_readiness": {next(iter(self.scope)): {"valves": {"status": "pending"}}},
            },
        }

    def test_current_166_line_607_spool_ros_scope_is_preserved_exactly(self):
        # Read the checked-in ROS snapshot only while preparing the input.
        ros = fabrication_skyline(as_of_date=date(2026, 9, 15))
        expected = Counter()
        for row in segments(ros, "forecast"):
            expected[row["line"]] += row["spools"]
        self.assertEqual(len(expected), 166)
        self.assertEqual(sum(expected.values()), 607)
        before = deepcopy(ros)
        with patch("apps.core.real_sources._datafy_conn", side_effect=AssertionError("No operational database")), \
                patch("pathlib.Path.read_text", side_effect=AssertionError("Only supplied ROS scope")):
            payload = installation_skyline_sample(ros)
        planned = segments(payload, "forecast")
        self.assertEqual(len(planned), 166)
        self.assertEqual({row["line"]: row["spools"] for row in planned}, dict(expected))
        self.assertEqual(payload["kpis"]["scope_spools"], 607)
        self.assertEqual(payload["kpis"]["scheduled_spools"], 607)
        self.assertEqual(payload["kpis"]["line_count"], 166)
        self.assertEqual(ros, before)
        self.assertEqual(payload["source"]["scope_workbook"], ros["source"]["workbook"])
        self.assertEqual(payload["source"]["scope_snapshot_date"], ros["source"]["snapshot_date"])
        self.assertTrue(all(not row["line"].startswith("SIM-") for row in planned))
        active_columns = [bucket for bucket in payload["charts"]["dates"] if bucket["forecast"] or bucket["lookahead"]]
        self.assertGreaterEqual(len(active_columns), 18)
        first_date = date.fromisoformat(active_columns[0]["date"])
        last_date = date.fromisoformat(active_columns[-1]["date"])
        self.assertGreater((last_date - first_date).days, 100)
        self.assertEqual(payload["source"]["sample_version"], 4)
        # A longer axis must not change which lines are complete or their colors.
        self.assertEqual(payload["kpis"]["performed_line_count"], 45)
        self.assertEqual(payload["kpis"]["performed_spools"], 158)
        self.assertEqual(payload["kpis"]["on_time_line_count"], 5)
        self.assertEqual(payload["kpis"]["late_line_count"], 40)

    def test_real_scope_provenance_and_sample_progress_remain_distinct(self):
        ros = self.ros()
        before = deepcopy(ros)
        with patch("apps.core.real_sources._datafy_conn", side_effect=AssertionError("No operational database")), \
                patch("pathlib.Path.read_text", side_effect=AssertionError("No operational snapshot")):
            payload = installation_skyline_sample(ros)
        self.assertEqual(ros, before)
        self.assertTrue(payload["available"])
        self.assertEqual({row["line"]: row["spools"] for row in segments(payload, "forecast")}, self.scope)
        source = payload["source"]
        self.assertEqual(source["mode"], "installation")
        self.assertTrue(source["is_sample"])
        self.assertEqual(source["data_kind"], "sample")
        self.assertEqual(source["source_label"], "Sample data")
        self.assertEqual(source["scope_kind"], "real")
        self.assertEqual(source["scope_source"], "ROS")
        self.assertEqual(source["scope_workbook"], "ROS scope.xlsx")
        self.assertEqual(source["scope_snapshot_date"], "2026-09-03")
        self.assertEqual(source["scope_snapshot_label"], "03 Sep 26")
        self.assertEqual(source["as_of_date"], "2026-09-15")
        self.assertEqual(source["snapshot_date"], "2026-09-15")
        self.assertEqual(payload["charts"]["material_readiness"], {})
        self.assertFalse(source["material_readiness_available"])
        self.assertEqual(json.loads(payload["charts_json"]), payload["charts"])
        for band in ("forecast", "lookahead"):
            for row in segments(payload, band):
                self.assertEqual(row["spools"], self.scope[row["line"]])
                self.assertTrue(row["is_sample"])
                self.assertEqual(row["actual_finish"], "")
                self.assertFalse(row["actual_date_confirmed"])
                self.assertEqual(row["progress_source"], "Sample data")
                self.assertNotIn("fabrication_progress_pct", row)
                self.assertNotIn(row["date"], {"2099-12-03", "2099-12-04", "2099-12-11"})

    def test_refresh_and_reordering_keep_dates_stable_and_do_not_share_mutable_results(self):
        ros = self.ros()
        first = installation_skyline_sample(ros)
        self.assertEqual(first, installation_skyline_sample(ros))
        reordered = deepcopy(ros)
        reordered["charts"]["dates"].reverse()
        for bucket in reordered["charts"]["dates"]:
            bucket["forecast"].reverse()
            bucket["lookahead"].reverse()
        self.assertEqual(first, installation_skyline_sample(reordered))
        first["charts"]["dates"][0]["forecast"][0]["line"] = "Changed for this caller"
        self.assertEqual(installation_skyline_sample(ros), installation_skyline_sample(reordered))

    def test_ros_dates_progress_and_readiness_do_not_drive_simulated_installation(self):
        ros = self.ros()
        changed = deepcopy(ros)
        changed["source"]["as_of_date"] = "2037-01-01"
        changed["charts"]["material_readiness"] = {"other": {"supports": {"status": "ready"}}}
        for bucket in changed["charts"]["dates"]:
            bucket["date"] = "2037-01-02"
            for band in ("forecast", "lookahead"):
                for row in bucket[band]:
                    row.update(date="2037-01-01", dates=["2037-01-01"], status="partial",
                               performed_spools=0, progress_pct=37, actual_finish="2036-12-31")
        self.assertEqual(installation_skyline_sample(ros), installation_skyline_sample(changed))

    def test_shared_scope_rules_sum_forecast_fragments_without_double_counting_lookahead(self):
        ros = self.ros()
        line = '1.1/2"-DN-473601'
        other = '6"-DN-473604'
        ros["charts"]["dates"] = [
            {"forecast": [{"line": " " + line + " ", "spools": 2}],
             "lookahead": [{"line": line, "spools": 900}]},
            {"forecast": [{"line": line, "spools": 5}, {"line": other, "spools": 11}],
             "lookahead": [{"line": "LOOKAHEAD-ONLY", "spools": 100}]},
        ]
        result = installation_skyline_sample(ros)
        self.assertEqual({row["line"]: row["spools"] for row in segments(result, "forecast")}, {line: 7, other: 11})
        self.assertEqual(result["kpis"]["scope_spools"], 18)

    def test_lookahead_fallback_sums_segment_quantities_not_repeated_line_totals(self):
        ros = self.ros()
        line, other = list(self.scope)[:2]
        ros["charts"]["dates"] = [
            {"forecast": [], "lookahead": [
                {"line": line, "spools": 2, "line_spools": 7, "performed_spools": 2},
                {"line": other, "spools": 1, "line_spools": 1},
            ]},
            {"lookahead": [{"line": line, "spools": 5, "line_spools": 7, "performed_spools": 0}]},
        ]
        result = installation_skyline_sample(ros)
        self.assertEqual({row["line"]: row["spools"] for row in segments(result, "forecast")}, {line: 7, other: 1})
        self.assertEqual(result["kpis"]["scope_spools"], 8)

    def test_missing_failed_or_invalid_scope_stays_unavailable_without_synthetic_lines(self):
        inputs = [
            {},
            {"available": False, "error": "ROS source could not be refreshed", "charts": {"dates": []}},
            {"charts": {"dates": [{"forecast": [
                {"line": "ZERO", "spools": 0}, {"line": "NEGATIVE", "spools": -3},
                {"line": "BOOLEAN", "spools": True}, {"line": "FLOAT", "spools": 2.0},
                {"line": "STRING", "spools": "7"}, {"line": "NONE", "spools": None},
                {"line": " ", "spools": 5},
            ], "lookahead": [{"line": "Not a forecast fallback", "spools": 10}]}]}},
        ]
        for ros in inputs:
            with self.subTest(ros=ros):
                before = deepcopy(ros)
                result = installation_skyline_sample(ros)
                self.assertFalse(result["available"])
                self.assertTrue(result["error"])
                self.assertEqual(result["charts"]["dates"], [])
                self.assertEqual(result["kpis"]["line_count"], 0)
                self.assertEqual(result["kpis"]["scope_spools"], 0)
                self.assertEqual(json.loads(result["charts_json"]), result["charts"])
                self.assertEqual(ros, before)

    def test_lower_band_only_contains_whole_lines_completed_by_the_sample_cutoff(self):
        payload = installation_skyline_sample(self.ros())
        planned = {row["line"]: row for row in segments(payload, "forecast")}
        completed = segments(payload, "lookahead")
        completed_ids = {row["line"] for row in completed}
        self.assertGreater(len(completed), 0)
        self.assertLess(len(completed), len(planned))
        self.assertEqual(len(completed_ids), len(completed))
        self.assertTrue(completed_ids.issubset(planned))
        self.assertEqual({row["status"] for row in completed}, {"on_time", "late"})
        for row in completed:
            self.assertLessEqual(row["date"], payload["source"]["as_of_date"])
            self.assertEqual(row["date"], row["completion_date"])
            self.assertEqual(row["date_kind"], "sample")
            self.assertEqual(row["completion_date_kind"], "sample")
            self.assertEqual(row["actual_finish"], "")
            self.assertFalse(row["actual_date_confirmed"])
            self.assertEqual(row["progress_pct"], 100)
            self.assertEqual(row["spools"], self.scope[row["line"]])
            self.assertEqual(row["performed_spools"], row["spools"])
            self.assertEqual(row["remaining_spools"], 0)
            self.assertEqual(row["planned_finish"], planned[row["line"]]["date"])
            expected_status = "on_time" if row["date"] <= row["planned_finish"] else "late"
            self.assertEqual(row["status"], expected_status)
        for line, row in planned.items():
            self.assertEqual(row["date_kind"], "planned")
            self.assertEqual(row["date"], row["planned_finish"])
            self.assertEqual(row["dates"], [row["date"]])
            if line not in completed_ids:
                self.assertEqual(row["actual_finish"], "")
                self.assertEqual(row["completion_date"], "")
                self.assertEqual(row["progress_pct"], 0)

    def test_week_buckets_and_status_totals_reconcile_with_exact_real_line_quantities(self):
        payload = installation_skyline_sample(self.ros())
        kpis, charts = payload["kpis"], payload["charts"]
        line_counts = Counter(row["status"] for row in segments(payload, "lookahead"))
        spool_counts = Counter()
        for row in segments(payload, "lookahead"):
            spool_counts[row["status"]] += row["spools"]
        for status, quantity in charts["status_totals"].items():
            self.assertEqual(quantity, spool_counts[status])
            self.assertEqual(charts["status_line_counts"][status], line_counts[status])
            self.assertEqual(kpis[f"{status}_spools"], quantity)
            self.assertEqual(kpis[f"{status}_line_count"], line_counts[status])
        self.assertEqual(kpis["scope_spools"], sum(self.scope.values()))
        self.assertEqual(kpis["performed_spools"] + kpis["remaining_spools"], sum(self.scope.values()))
        self.assertEqual(kpis["performed_line_count"] + kpis["remaining_line_count"], len(self.scope))
        self.assertEqual(kpis["performed_spools"], sum(charts["status_totals"].values()))
        self.assertEqual(kpis["confirmed_actual_spools"], 0)
        self.assertEqual(kpis["reported_spools"], 0)
        for bucket in charts["dates"]:
            week_end = date.fromisoformat(bucket["date"])
            self.assertEqual(week_end.weekday(), 4)
            for band in ("forecast", "lookahead"):
                self.assertEqual(bucket[f"{band}_total"], sum(row["spools"] for row in bucket[band]))
                for row in bucket[band]:
                    self.assertLessEqual(date.fromisoformat(row["date"]), week_end)
                    self.assertGreaterEqual(date.fromisoformat(row["date"]), week_end - timedelta(days=6))
            self.assertEqual(bucket["performed_total"], bucket["lookahead_total"])
            self.assertEqual(bucket["remaining_total"], 0)

    def test_simulated_dates_follow_daily_installation_shape_scaled_to_real_scope(self):
        payload = installation_skyline_sample(self.ros())
        rundown = installation_rundown_sample("piping")
        sample_scope = rundown["kpis"]["scope_total"]
        real_scope = sum(self.scope.values())
        self.assertNotEqual(real_scope, sample_scope)
        self.assertEqual(payload["source"]["as_of_date"], rundown["source"]["as_of_date"])
        cutoff = date.fromisoformat(payload["source"]["as_of_date"])
        for skyline_band, rundown_series in (("forecast", "baseline"), ("lookahead", "lookahead")):
            cumulative_daily = 0
            rows = segments(payload, skyline_band)
            for day, daily in zip(rundown["charts"]["dates"], rundown["charts"][f"{rundown_series}_total"]):
                expanded_date = cutoff + timedelta(days=(date.fromisoformat(day) - cutoff).days * 4)
                if skyline_band == "lookahead" and expanded_date > cutoff:
                    break
                cumulative_daily += int(daily or 0)
                scaled_capacity = cumulative_daily * real_scope // sample_scope
                complete_spools = sum(row["spools"] for row in rows if row["date"] <= expanded_date.isoformat())
                self.assertLessEqual(complete_spools, scaled_capacity)
                # Work within one unfinished real line does not complete a box.
                self.assertLess(scaled_capacity - complete_spools, max(self.scope.values()))

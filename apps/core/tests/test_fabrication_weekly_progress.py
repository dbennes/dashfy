from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.fabrication_source import (
    _add_time_phased_tons,
    _charts_payload,
    _reported_progress_by_week,
    _weekly_progress_report_rows,
    overall_pct,
    overall_value,
    stage_is_applicable,
    stage_value,
)


class FabricationWeeklyProgressCompatibilityTests(SimpleTestCase):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 15)

    def test_curve_includes_every_week_between_sparse_points(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06-05": Decimal("5"),
                "2026-07-03": Decimal("5"),
            },
        }]

        curve = _charts_payload(rows, {})["curve"]

        self.assertEqual(
            curve["labels"],
            ["05/06/26", "12/06/26", "19/06/26", "26/06/26", "03/07/26"],
        )
        self.assertEqual(curve["planned"], [50.0, 50.0, 50.0, 50.0, 100.0])
        self.assertEqual(curve["axis_labels"], ["Jun/26", "", "", "", "Jul/26"])
        self.assertEqual(curve["granularity"], "week")
        self.assertEqual(curve["week_ending"], "friday")
        self.assertEqual(curve["periods"][0], "2026-06-05")

    def test_curve_shows_only_report_weeks_after_one_zero_baseline(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06-05": Decimal("5"),
                "2026-11-27": Decimal("5"),
            },
        }]
        reported = _reported_progress_by_week([
            {"id": 1, "report_date": date(2026, 8, 14), "reported_overall_pct": "17.16531969256482"},
            {"id": 2, "report_date": date(2026, 8, 18), "reported_overall_pct": "18.765"},
            {"id": 3, "report_date": date(2026, 10, 1), "reported_overall_pct": "25.5"},
        ])

        with patch("apps.core.fabrication_source.date_cls", self.FixedDate):
            curve = _charts_payload(
                rows,
                {"2026-07-03": Decimal("9")},
                reported,
                {
                    "2026-08-14": date(2026, 8, 14),
                    "2026-08-21": date(2026, 8, 18),
                    "2026-10-02": date(2026, 10, 1),
                },
            )["curve"]

        self.assertEqual(reported, {
            "2026-08-14": Decimal("17.16531969256482"),
            "2026-08-21": Decimal("18.765"),
            "2026-10-02": Decimal("25.5"),
        })
        actual = dict(zip(curve["labels"], curve["actual"]))
        self.assertEqual(actual["05/06/26"], 0.0)
        self.assertIsNone(actual["07/08/26"])
        self.assertAlmostEqual(actual["14/08/26"], 17.16531969256482)
        self.assertEqual(actual["21/08/26"], 18.765)
        self.assertEqual(actual["02/10/26"], 25.5)
        self.assertIsNone(actual["09/10/26"])
        self.assertIsNone(actual["16/10/26"])
        self.assertIsNone(actual["23/10/26"])
        reports = dict(zip(curve["labels"], curve["report_dates"]))
        point_types = dict(zip(curve["labels"], curve["point_types"]))
        self.assertEqual(reports["14/08/26"], "2026-08-14")
        self.assertEqual(reports["21/08/26"], "2026-08-18")
        self.assertEqual(reports["02/10/26"], "2026-10-01")
        self.assertIsNone(reports["09/10/26"])
        self.assertIsNone(reports["23/10/26"])
        self.assertEqual(point_types["05/06/26"], "baseline")
        self.assertIsNone(point_types["07/08/26"])
        self.assertEqual(point_types["14/08/26"], "reported")
        self.assertEqual(curve["actual_source"], "weekly_workbook")

    def test_curve_displays_the_exact_column_w_total_as_17_17_percent(self):
        class ReportDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 8, 21)

        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06-05": Decimal("5"),
                "2026-12-04": Decimal("5"),
            },
        }]

        with patch("apps.core.fabrication_source.date_cls", ReportDate):
            curve = _charts_payload(
                rows,
                {},
                {"2026-08-14": Decimal("17.16531969256482")},
            )["curve"]

        actual = dict(zip(curve["labels"], curve["actual"]))
        self.assertEqual(actual["05/06/26"], 0.0)
        self.assertIsNone(actual["07/08/26"])
        self.assertAlmostEqual(actual["14/08/26"], 17.16531969256482)
        self.assertIsNone(actual["21/08/26"])
        self.assertIsNone(actual["28/08/26"])

    def test_curve_keeps_past_and_future_reports_only_on_their_weeks(self):
        class ReportDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 8, 21)

        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06-05": Decimal("5"),
                "2026-12-04": Decimal("5"),
            },
        }]

        with patch("apps.core.fabrication_source.date_cls", ReportDate):
            curve = _charts_payload(
                rows,
                {},
                {
                    "2026-07-10": Decimal("10.25"),
                    "2026-09-04": Decimal("20.2"),
                },
                {
                    "2026-07-10": date(2026, 7, 10),
                    "2026-09-04": date(2026, 9, 3),
                },
            )["curve"]

        actual = dict(zip(curve["periods"], curve["actual"]))
        report_dates = dict(zip(curve["periods"], curve["report_dates"]))
        self.assertEqual(actual["2026-06-05"], 0.0)
        self.assertEqual(actual["2026-07-10"], 10.25)
        self.assertIsNone(actual["2026-07-17"])
        self.assertEqual(actual["2026-09-04"], 20.2)
        self.assertIsNone(actual["2026-09-11"])
        self.assertEqual(report_dates["2026-07-10"], "2026-07-10")
        self.assertEqual(report_dates["2026-09-04"], "2026-09-03")
        self.assertIsNone(report_dates["2026-09-11"])

    def test_curve_adds_previous_friday_baseline_when_report_precedes_plan(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {"2026-09-04": Decimal("10")},
        }]

        curve = _charts_payload(
            rows,
            {},
            {"2026-08-14": Decimal("17.16531969256482")},
        )["curve"]

        self.assertEqual(curve["periods"][0], "2026-08-07")
        self.assertEqual(curve["actual"][0], 0.0)
        self.assertAlmostEqual(curve["actual"][1], 17.16531969256482)
        self.assertEqual(curve["point_types"][:2], ["baseline", "reported"])
        self.assertTrue(all(value is None for value in curve["actual"][2:]))

    def test_report_curve_does_not_add_the_current_week_outside_its_data_range(self):
        class ReportDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 8, 21)

        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {"2026-06-05": Decimal("10")},
        }]

        with patch("apps.core.fabrication_source.date_cls", ReportDate):
            curve = _charts_payload(
                rows,
                {},
                {"2026-07-10": Decimal("17.17")},
                {"2026-07-10": date(2026, 7, 9)},
            )["curve"]

        self.assertEqual(curve["periods"][-1], "2026-07-10")
        self.assertNotIn("2026-08-21", curve["periods"])
        self.assertEqual(curve["point_types"][-1], "reported")

    def test_same_week_uses_latest_report_date_and_id(self):
        reported = _reported_progress_by_week([
            {"id": 5, "report_date": date(2026, 8, 11), "reported_overall_pct": "16"},
            {"id": 2, "report_date": date(2026, 8, 14), "reported_overall_pct": "17.17"},
            {"id": 9, "report_date": date(2026, 8, 14), "reported_overall_pct": "17.5"},
        ])

        self.assertEqual(reported, {"2026-08-14": Decimal("17.5")})

    def test_curve_falls_back_entirely_to_legacy_tons_delta_without_reports(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06-05": Decimal("5"),
                "2026-11-27": Decimal("5"),
            },
        }]

        with patch("apps.core.fabrication_source.date_cls", self.FixedDate):
            curve = _charts_payload(
                rows,
                {"2026-06-05": Decimal("2"), "2026-08-14": Decimal("1")},
                {},
            )["curve"]

        actual = dict(zip(curve["labels"], curve["actual"]))
        self.assertEqual(actual["05/06/26"], 20.0)
        self.assertEqual(actual["12/06/26"], 20.0)
        self.assertEqual(actual["14/08/26"], 30.0)
        self.assertEqual(actual["16/10/26"], 30.0)
        self.assertIsNone(actual["23/10/26"])
        self.assertEqual(curve["actual_source"], "dated_progress_entries")

    def test_planned_weight_is_split_by_inclusive_days_across_friday_buckets(self):
        points = {}

        _add_time_phased_tons(
            points,
            date(2026, 8, 14),
            date(2026, 8, 15),
            Decimal("10"),
        )

        self.assertEqual(points, {
            "2026-08-14": Decimal("5"),
            "2026-08-21": Decimal("5"),
        })

    def test_curve_excludes_structural_plan_from_column_w_scope(self):
        rows = [
            {
                "_weight": Decimal("10"),
                "campaign": "Campaign A",
                "discipline": "piping",
                "overall": 0,
                "_planned_points": {"2026-09-04": Decimal("10")},
            },
            {
                "_weight": Decimal("90"),
                "campaign": "Campaign A",
                "discipline": "structural",
                "overall": 0,
                "_planned_points": {"2026-01-02": Decimal("90")},
            },
        ]

        curve = _charts_payload(rows, {})["curve"]

        self.assertEqual(curve["labels"], ["04/09/26"])
        self.assertEqual(curve["planned"], [100.0])
        self.assertEqual(curve["scope"], "piping_iso_lines")

    def test_missing_report_table_stops_before_querying_it(self):
        queries = []

        def rows_reader(_cursor, query):
            queries.append(query)
            return [{"relation_name": None}]

        self.assertEqual(_weekly_progress_report_rows(object(), rows_reader), [])
        self.assertEqual(len(queries), 1)
        self.assertIn("to_regclass", queries[0])

    def test_empty_report_table_returns_no_rows_for_legacy_fallback(self):
        queries = []

        def rows_reader(_cursor, query):
            queries.append(query)
            if len(queries) == 1:
                return [{"relation_name": "fabrication_fabricationweeklyprogressreport"}]
            return []

        self.assertEqual(_weekly_progress_report_rows(object(), rows_reader), [])
        self.assertEqual(len(queries), 2)
        self.assertIn("reported_overall_pct", queries[1])

    def test_reads_exact_weekly_overall_from_shared_stages_json(self):
        stages = {
            "prefabrication": {"pct": 99.5173745, "duration_weight": 90},
            "_weekly_progress": {
                "schema": 1,
                "source": "epc1_iso_weekly",
                "report_date": "2026-08-14",
                "overall_pct": "74.9563492063492",
                "pwht_required": True,
            },
        }

        self.assertEqual(overall_value(stages), Decimal("74.9563492063492"))
        self.assertEqual(overall_pct(stages), 75)
        self.assertEqual(stage_value(stages, "prefabrication"), Decimal("99.5173745"))

    def test_invalid_weekly_marker_falls_back_to_existing_p6_math(self):
        stages = {
            "prefabrication": {"pct": 40, "duration_weight": 1},
            "welding": {"pct": 60, "duration_weight": 1},
            "_weekly_progress": {
                "schema": 1,
                "source": "unexpected_source",
                "report_date": "2026-08-14",
                "overall_pct": "99.99",
                "pwht_required": False,
            },
        }

        self.assertEqual(overall_value(stages), Decimal("50"))
        self.assertEqual(overall_pct(stages), 50)

    def test_no_pwht_marker_hides_but_does_not_delete_p6_schedule_stage(self):
        stages = {
            "pwht": {
                "pct": 0,
                "duration_weight": 3,
                "plan_start": "2026-09-01",
                "acts": [{"id": "PWHT-1", "pct": 0}],
            },
            "_weekly_progress": {
                "schema": 1,
                "source": "epc1_iso_weekly",
                "report_date": "2026-08-14",
                "overall_pct": "12.5",
                "pwht_required": False,
            },
        }

        self.assertFalse(stage_is_applicable(stages, "pwht"))
        self.assertEqual(stages["pwht"]["duration_weight"], 3)
        self.assertEqual(stages["pwht"]["acts"][0]["id"], "PWHT-1")

    def test_report_date_with_suffix_is_rejected_like_spdm(self):
        stages = {
            "welding": {"pct": 40, "duration_weight": 1},
            "_weekly_progress": {
                "schema": 1,
                "source": "epc1_iso_weekly",
                "report_date": "2026-08-14T10:00:00",
                "overall_pct": "99.99",
                "pwht_required": False,
            },
        }

        self.assertEqual(overall_value(stages), Decimal("40"))

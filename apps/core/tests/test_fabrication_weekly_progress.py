from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.fabrication_source import (
    _charts_payload,
    _reported_progress_by_month,
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

    def test_curve_includes_every_month_between_sparse_points(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06": Decimal("5"),
                "2026-11": Decimal("5"),
            },
        }]

        curve = _charts_payload(rows, {})["curve"]

        self.assertEqual(
            curve["labels"],
            ["Jun/26", "Jul/26", "Aug/26", "Sep/26", "Oct/26", "Nov/26"],
        )
        self.assertEqual(curve["planned"], [50.0, 50.0, 50.0, 50.0, 50.0, 100.0])

    def test_curve_uses_latest_absolute_report_and_carries_it_forward(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06": Decimal("5"),
                "2026-11": Decimal("5"),
            },
        }]
        reported = _reported_progress_by_month([
            {"id": 1, "report_date": date(2026, 8, 14), "reported_overall_pct": "17.16531969256482"},
            {"id": 2, "report_date": date(2026, 8, 21), "reported_overall_pct": "18.765"},
            {"id": 3, "report_date": date(2026, 10, 1), "reported_overall_pct": "25.5"},
        ])

        with patch("apps.core.fabrication_source.date_cls", self.FixedDate):
            curve = _charts_payload(
                rows,
                {"2026-07": Decimal("9")},
                reported,
            )["curve"]

        self.assertEqual(reported, {
            "2026-08": Decimal("18.765"),
            "2026-10": Decimal("25.5"),
        })
        self.assertEqual(curve["actual"], [None, None, 18.77, 18.77, 25.5, None])
        self.assertEqual(curve["actual_source"], "weekly_workbook")

    def test_curve_displays_the_exact_column_w_total_as_17_17_percent(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06": Decimal("5"),
                "2026-11": Decimal("5"),
            },
        }]

        with patch("apps.core.fabrication_source.date_cls", self.FixedDate):
            curve = _charts_payload(
                rows,
                {},
                {"2026-08": Decimal("17.16531969256482")},
            )["curve"]

        self.assertEqual(curve["actual"], [None, None, 17.17, 17.17, 17.17, None])

    def test_curve_falls_back_entirely_to_legacy_tons_delta_without_reports(self):
        rows = [{
            "_weight": Decimal("10"),
            "campaign": "Campaign A",
            "discipline": "piping",
            "overall": 0,
            "_planned_points": {
                "2026-06": Decimal("5"),
                "2026-11": Decimal("5"),
            },
        }]

        with patch("apps.core.fabrication_source.date_cls", self.FixedDate):
            curve = _charts_payload(
                rows,
                {"2026-06": Decimal("2"), "2026-08": Decimal("1")},
                {},
            )["curve"]

        self.assertEqual(curve["actual"], [20.0, 20.0, 30.0, 30.0, 30.0, None])
        self.assertEqual(curve["actual_source"], "tons_delta")

    def test_curve_excludes_structural_plan_from_column_w_scope(self):
        rows = [
            {
                "_weight": Decimal("10"),
                "campaign": "Campaign A",
                "discipline": "piping",
                "overall": 0,
                "_planned_points": {"2026-09": Decimal("10")},
            },
            {
                "_weight": Decimal("90"),
                "campaign": "Campaign A",
                "discipline": "structural",
                "overall": 0,
                "_planned_points": {"2026-01": Decimal("90")},
            },
        ]

        curve = _charts_payload(rows, {})["curve"]

        self.assertEqual(curve["labels"], ["Sep/26"])
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

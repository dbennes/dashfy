import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import skyline_source
from apps.core.skyline_source import fabrication_skyline, fabrication_skyline_safe


class FabricationSkylineSnapshotTests(SimpleTestCase):
    def test_snapshot_matches_the_runddown_scope(self):
        payload = fabrication_skyline(as_of_date=date(2026, 9, 3))
        weeks = payload["charts"]["weeks"]

        self.assertTrue(payload["available"])
        self.assertEqual(
            payload["source"]["workbook"],
            "datafy-material-requisition-20260902-0954 para curva Piping 02.09.26 (003) (002).xlsx",
        )
        self.assertEqual(payload["source"]["worksheet"], "Planilha1 / Runddown")
        self.assertEqual(payload["source"]["range"], "A1:E176 / F5:G180")
        self.assertEqual(payload["source"]["forecast_scope"], "Planilha1!A1:E176")
        self.assertEqual(payload["source"]["actual_scope"], "Runddown!F5:G180")
        self.assertEqual(payload["source"]["snapshot_date"], "2026-09-02")
        self.assertEqual(payload["source"]["as_of_date"], "2026-09-03")
        self.assertEqual(payload["kpis"]["line_count"], 166)
        self.assertEqual(payload["kpis"]["entry_count"], 175)
        self.assertEqual(payload["kpis"]["scope_spools"], 607)
        self.assertEqual(payload["kpis"]["actual_line_count"], 3)
        self.assertEqual(payload["kpis"]["actual_spools"], 21)
        self.assertEqual(len(weeks), 15)
        self.assertEqual(weeks[0]["date"], "2026-08-21")
        self.assertEqual(weeks[-1]["date"], "2026-11-27")
        self.assertEqual(sum(week["forecast_total"] for week in weeks), 607)
        self.assertEqual(sum(week["actual_total"] for week in weeks), 21)
        self.assertNotIn("status_totals", payload["charts"])
        self.assertNotIn("status_line_counts", payload["charts"])

    def test_repeated_line_keeps_its_baseline_for_every_split(self):
        payload = fabrication_skyline(as_of_date=date(2026, 9, 3))
        weeks = {week["date"]: week for week in payload["charts"]["weeks"]}

        forecast_segment = next(
            item for item in weeks["2026-08-28"]["forecast"]
            if item["line"] == '14"-PM-033031'
        )
        actual_segment = next(
            item for item in weeks["2026-08-28"]["actual"]
            if item["line"] == '14"-PM-033031'
        )

        self.assertEqual(forecast_segment["spools"], 4)
        self.assertEqual(actual_segment["spools"], 1)

    def test_actual_contains_only_lookahead_entries_before_the_as_of_date(self):
        payload = fabrication_skyline(as_of_date=date(2026, 9, 3))
        actual_entries = [
            entry
            for week in payload["charts"]["weeks"]
            for entry in week["actual"]
        ]

        self.assertEqual(sum(entry["spools"] for entry in actual_entries), 21)
        self.assertTrue(actual_entries)
        self.assertEqual(
            {entry["line"]: entry["spools"] for entry in actual_entries},
            {
                '14"-PM-033030': 5,
                '14"-PM-033031': 1,
                '4"-PG-313050': 15,
            },
        )
        self.assertTrue(
            all(
                actual_date < "2026-09-03"
                for entry in actual_entries
                for actual_date in entry["dates"]
            )
        )

    def test_only_fully_empty_week_can_be_omitted_from_the_view(self):
        weeks = fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["weeks"]
        visible = [
            week for week in weeks
            if week["forecast"] or week["actual"]
            or week["forecast_total"] or week["actual_total"]
        ]
        hidden = [week["date"] for week in weeks if week not in visible]

        self.assertEqual(hidden, ["2026-10-16"])
        self.assertEqual(sum(week["forecast_total"] for week in visible), 607)
        self.assertEqual(sum(week["actual_total"] for week in visible), 21)
        self.assertEqual(sum(len(week["forecast"]) for week in visible), 166)
        self.assertEqual(sum(len(week["actual"]) for week in visible), 3)

    def test_actual_advances_with_the_application_date(self):
        first = fabrication_skyline(as_of_date=date(2026, 9, 3))
        on_next_batch_date = fabrication_skyline(as_of_date=date(2026, 9, 6))
        later = fabrication_skyline(as_of_date=date(2026, 9, 7))

        self.assertEqual(first["kpis"]["actual_spools"], 21)
        self.assertEqual(on_next_batch_date["kpis"]["actual_spools"], 21)
        self.assertEqual(later["kpis"]["actual_spools"], 48)
        self.assertEqual(later["source"]["as_of_date"], "2026-09-07")
        self.assertTrue(
            all(
                actual_date < "2026-09-07"
                for week in later["charts"]["weeks"]
                for entry in week["actual"]
                for actual_date in entry["dates"]
            )
        )

    def test_last_release_dates_are_derived_from_the_two_schedules(self):
        kpis = fabrication_skyline(as_of_date=date(2026, 9, 3))["kpis"]

        self.assertEqual(kpis["baseline_last_release_label"], "25 Nov 26")
        self.assertEqual(kpis["lookahead_last_release_label"], "14 Dec 26")
        self.assertEqual(kpis["last_release_variance_days"], 19)

    def test_safe_loader_degrades_without_breaking_s03(self):
        missing = Path("definitely-missing-fabrication-skyline.json")
        with (
            patch("apps.core.skyline_source.SKYLINE_DATA_PATH", missing),
            patch("apps.core.skyline_source.logger.exception") as log_exception,
        ):
            payload = fabrication_skyline_safe()

        self.assertFalse(payload["available"])
        self.assertEqual(payload["charts"]["weeks"], [])
        self.assertEqual(payload["error"], "the source snapshot could not be read.")
        log_exception.assert_called_once()

    def test_snapshot_fails_closed_if_actual_dates_are_reordered(self):
        raw = json.loads(skyline_source.SKYLINE_DATA_PATH.read_text(encoding="utf-8"))
        raw["actual_dates"][0] = "2026-12-03"

        with self.assertRaisesRegex(ValueError, "no longer matches Runddown F:G"):
            skyline_source._validated_snapshot(raw)

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import skyline_source
from apps.core.skyline_source import fabrication_skyline, fabrication_skyline_safe


class FabricationSkylineSnapshotTests(SimpleTestCase):
    def test_snapshot_matches_the_full_lookahead_scope(self):
        payload = fabrication_skyline(as_of_date=date(2026, 9, 3))
        weeks = payload["charts"]["weeks"]

        self.assertTrue(payload["available"])
        self.assertEqual(
            payload["source"]["workbook"],
            "Cópia de datafy-material-requisition-20260902-0954 para curva Piping 02.09.26 (003) atualizado 22h.xlsx",
        )
        self.assertEqual(payload["source"]["worksheet"], "Planilha1 / Runddown")
        self.assertEqual(payload["source"]["range"], "A1:E176 / F5:G180")
        self.assertEqual(payload["source"]["forecast_scope"], "Planilha1!A1:E176")
        self.assertEqual(payload["source"]["lookahead_scope"], "Runddown!F5:G180")
        self.assertEqual(payload["source"]["snapshot_date"], "2026-09-02")
        self.assertEqual(payload["source"]["revision_timestamp"], "2026-09-03T21:07:18")
        self.assertEqual(
            payload["source"]["workbook_sha256"],
            "FA5D662EAD24A555985488130F3528F7F9AB5A666FDF919D7A65A5C6CBBEE9BD",
        )
        self.assertEqual(payload["source"]["as_of_date"], "2026-09-03")
        self.assertEqual(payload["kpis"]["line_count"], 166)
        self.assertEqual(payload["kpis"]["entry_count"], 175)
        self.assertEqual(payload["kpis"]["scope_spools"], 607)
        self.assertEqual(payload["kpis"]["performed_line_count"], 10)
        self.assertEqual(payload["kpis"]["performed_spools"], 48)
        self.assertEqual(payload["kpis"]["upcoming_line_count"], 164)
        self.assertEqual(payload["kpis"]["upcoming_spools"], 559)
        self.assertEqual(payload["kpis"]["partial_line_count"], 8)
        self.assertEqual(payload["kpis"]["partial_spools"], 39)
        self.assertEqual(payload["kpis"]["late_line_count"], 2)
        self.assertEqual(payload["kpis"]["late_spools"], 9)
        self.assertEqual(payload["kpis"]["on_time_line_count"], 0)
        self.assertEqual(payload["kpis"]["on_time_spools"], 0)
        self.assertEqual(len(weeks), 18)
        self.assertEqual(weeks[0]["date"], "2026-08-21")
        self.assertEqual(weeks[-1]["date"], "2026-12-18")
        self.assertEqual(sum(week["forecast_total"] for week in weeks), 607)
        self.assertEqual(sum(week["lookahead_total"] for week in weeks), 607)
        self.assertEqual(sum(len(week["forecast"]) for week in weeks), 166)
        self.assertEqual(sum(len(week["lookahead"]) for week in weeks), 175)
        self.assertEqual(
            payload["charts"]["status_totals"],
            {"on_time": 0, "late": 9, "partial": 39, "upcoming": 559},
        )

    def test_completed_late_line_keeps_one_status_across_its_splits(self):
        weeks = {
            week["date"]: week
            for week in fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["weeks"]
        }

        forecast_segment = next(
            item for item in weeks["2026-08-28"]["forecast"]
            if item["line"] == '14"-PM-033031'
        )
        first_lookahead = next(
            item for item in weeks["2026-08-28"]["lookahead"]
            if item["line"] == '14"-PM-033031'
        )
        second_lookahead = next(
            item for item in weeks["2026-09-04"]["lookahead"]
            if item["line"] == '14"-PM-033031'
        )

        self.assertEqual(forecast_segment["spools"], 4)
        self.assertEqual((first_lookahead["spools"], first_lookahead["status"]), (1, "late"))
        self.assertEqual((second_lookahead["spools"], second_lookahead["status"]), (3, "late"))

    def test_partial_line_splits_past_yellow_from_future_gray(self):
        weeks = {
            week["date"]: week
            for week in fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["weeks"]
        }

        performed = next(
            item for item in weeks["2026-08-28"]["lookahead"]
            if item["line"] == '4"-PG-313050'
        )
        upcoming = next(
            item for item in weeks["2026-09-18"]["lookahead"]
            if item["line"] == '4"-PG-313050'
        )

        self.assertEqual((performed["spools"], performed["status"]), (15, "partial"))
        self.assertEqual((upcoming["spools"], upcoming["status"]), (1, "upcoming"))

    def test_every_lookahead_row_is_visible_and_no_week_is_empty(self):
        weeks = fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["weeks"]

        self.assertFalse(any(not week["forecast"] and not week["lookahead"] for week in weeks))
        self.assertEqual(sum(week["lookahead_total"] for week in weeks), 607)
        self.assertEqual(sum(len(week["lookahead"]) for week in weeks), 175)
        self.assertTrue(
            all(
                segment["status"] in {"on_time", "late", "partial", "upcoming"}
                for week in weeks
                for segment in week["lookahead"]
            )
        )

    def test_cutoff_is_strict_and_statuses_advance_with_the_date(self):
        on_batch_date = fabrication_skyline(as_of_date=date(2026, 9, 14))
        next_day = fabrication_skyline(as_of_date=date(2026, 9, 15))

        self.assertEqual(on_batch_date["kpis"]["performed_spools"], 48)
        self.assertEqual(on_batch_date["kpis"]["upcoming_spools"], 559)
        self.assertEqual(next_day["kpis"]["performed_spools"], 56)
        self.assertEqual(next_day["kpis"]["upcoming_spools"], 551)
        self.assertEqual(next_day["source"]["as_of_date"], "2026-09-15")

    def test_status_precedence_covers_all_four_states(self):
        raw = {
            "schema": 3,
            "source": {},
            "columns": ["line", "baseline_date", "lookahead_date", "spools"],
            "rows": [
                ["PARTIAL", "2026-09-01", "2026-09-02", 1],
                ["PARTIAL", "2026-09-01", "2026-09-03", 2],
                ["LATE", "2026-09-01", "2026-09-02", 3],
                ["ON-TIME", "2026-09-02", "2026-09-02", 4],
            ],
        }
        _, rows = skyline_source._validated_snapshot(raw)
        segments = [
            segment
            for week in skyline_source._weekly_segments(rows, as_of_date=date(2026, 9, 3))
            for segment in week["lookahead"]
        ]
        by_line_and_status = {
            (segment["line"], segment["status"]): segment["spools"]
            for segment in segments
        }

        self.assertEqual(by_line_and_status[("PARTIAL", "partial")], 1)
        self.assertEqual(by_line_and_status[("PARTIAL", "upcoming")], 2)
        self.assertEqual(by_line_and_status[("LATE", "late")], 3)
        self.assertEqual(by_line_and_status[("ON-TIME", "on_time")], 4)

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

    def test_schema_two_snapshot_is_rejected(self):
        raw = json.loads(skyline_source.SKYLINE_DATA_PATH.read_text(encoding="utf-8"))
        raw["schema"] = 2

        with self.assertRaisesRegex(ValueError, "unsupported skyline data schema"):
            skyline_source._validated_snapshot(raw)

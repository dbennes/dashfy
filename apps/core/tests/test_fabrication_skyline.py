import json
from collections import Counter
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import skyline_source
from apps.core.skyline_source import fabrication_skyline, fabrication_skyline_safe


class FabricationSkylineSnapshotTests(SimpleTestCase):
    def test_snapshot_matches_the_full_lookahead_scope(self):
        payload = fabrication_skyline(as_of_date=date(2026, 9, 3))
        date_buckets = payload["charts"]["dates"]

        self.assertTrue(payload["available"])
        self.assertEqual(
            payload["source"]["workbook"],
            "Cópia de datafy-material-requisition-20260902-0954 para curva Piping 02.09.26 (003) atualizado 22h.xlsx",
        )
        self.assertEqual(payload["source"]["worksheet"], "Planilha1")
        self.assertEqual(payload["source"]["range"], "A1:E176")
        self.assertEqual(payload["source"]["forecast_scope"], "Planilha1!A1:E176")
        self.assertEqual(payload["source"]["lookahead_scope"], "Planilha1!A1:E176")
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
        self.assertEqual(payload["kpis"]["remaining_line_count"], 164)
        self.assertEqual(payload["kpis"]["remaining_spools"], 559)
        self.assertEqual(payload["kpis"]["upcoming_line_count"], 164)
        self.assertEqual(payload["kpis"]["upcoming_spools"], 559)
        self.assertEqual(payload["kpis"]["partial_line_count"], 8)
        self.assertEqual(payload["kpis"]["partial_spools"], 39)
        self.assertEqual(payload["kpis"]["late_line_count"], 2)
        self.assertEqual(payload["kpis"]["late_spools"], 9)
        self.assertEqual(payload["kpis"]["on_time_line_count"], 0)
        self.assertEqual(payload["kpis"]["on_time_spools"], 0)
        self.assertEqual(len(date_buckets), 18)
        self.assertEqual(date_buckets[0]["date"], "2026-08-21")
        self.assertEqual(date_buckets[-1]["date"], "2026-12-18")
        self.assertEqual(sum(item["forecast_total"] for item in date_buckets), 607)
        self.assertEqual(sum(item["lookahead_total"] for item in date_buckets), 607)
        self.assertEqual(sum(item["performed_total"] for item in date_buckets), 48)
        self.assertEqual(sum(item["remaining_total"] for item in date_buckets), 559)
        self.assertEqual(sum(len(item["forecast"]) for item in date_buckets), 166)
        self.assertEqual(sum(len(item["lookahead"]) for item in date_buckets), 175)
        self.assertEqual(
            payload["charts"]["status_totals"],
            {"on_time": 0, "late": 9, "partial": 39, "upcoming": 559},
        )

    def test_completed_late_line_keeps_one_status_across_its_splits(self):
        dates = {
            item["date"]: item
            for item in fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["dates"]
        }

        forecast_segment = next(
            item for item in dates["2026-08-28"]["forecast"]
            if item["line"] == '14"-PM-033031'
        )
        first_actual = next(
            item for item in dates["2026-08-28"]["lookahead"]
            if item["line"] == '14"-PM-033031'
        )
        second_actual = next(
            item for item in dates["2026-09-04"]["lookahead"]
            if item["line"] == '14"-PM-033031'
        )

        self.assertEqual(forecast_segment["spools"], 4)
        self.assertEqual((first_actual["spools"], first_actual["status"]), (1, "late"))
        self.assertEqual((second_actual["spools"], second_actual["status"]), (3, "late"))
        self.assertEqual(first_actual["line_spools"], 4)
        self.assertEqual(first_actual["line_performed_spools"], 4)
        self.assertEqual(first_actual["progress_pct"], 100.0)
        self.assertEqual(first_actual["dates"], ["2026-08-24"])
        self.assertEqual(second_actual["dates"], ["2026-09-02"])

    def test_single_axis_places_each_series_in_its_own_schedule_period(self):
        raw = json.loads(skyline_source.SKYLINE_DATA_PATH.read_text(encoding="utf-8"))
        payload = fabrication_skyline(as_of_date=date(2026, 9, 3))
        dates = {item["date"]: item for item in payload["charts"]["dates"]}

        self.assertNotIn("2026-09-02", dates)
        self.assertNotIn("2026-09-03", dates)
        self.assertEqual(dates["2026-09-04"]["forecast_total"], 41)
        self.assertEqual(len(dates["2026-09-04"]["forecast"]), 6)
        self.assertEqual(dates["2026-09-04"]["lookahead_total"], 27)
        self.assertEqual(dates["2026-09-04"]["performed_total"], 27)
        self.assertEqual(dates["2026-09-04"]["remaining_total"], 0)
        self.assertEqual(len(dates["2026-09-04"]["lookahead"]), 8)

        expected_by_baseline = Counter()
        expected_by_lookahead = Counter()
        for _, baseline_date, lookahead_date, spools in raw["rows"]:
            expected_by_baseline[skyline_source._week_ending_friday(date.fromisoformat(baseline_date)).isoformat()] += spools
            expected_by_lookahead[skyline_source._week_ending_friday(date.fromisoformat(lookahead_date)).isoformat()] += spools
        rendered_forecast = Counter()
        rendered_lookahead = Counter()
        for date_bucket in dates.values():
            for segment in date_bucket["forecast"]:
                self.assertEqual(segment["dates"], [segment["date"]])
                self.assertEqual(
                    skyline_source._week_ending_friday(date.fromisoformat(segment["date"])).isoformat(),
                    date_bucket["date"],
                )
                rendered_forecast[date_bucket["date"]] += segment["spools"]
            for segment in date_bucket["lookahead"]:
                self.assertTrue(all(
                    skyline_source._week_ending_friday(date.fromisoformat(value)).isoformat()
                    == date_bucket["date"]
                    for value in segment["dates"]
                ))
                rendered_lookahead[date_bucket["date"]] += segment["spools"]
        self.assertEqual(rendered_forecast, expected_by_baseline)
        self.assertEqual(rendered_lookahead, expected_by_lookahead)

    def test_partial_line_keeps_actual_and_future_dates_with_shared_progress(self):
        dates = {
            item["date"]: item
            for item in fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["dates"]
        }

        performed = next(
            item for item in dates["2026-08-28"]["lookahead"]
            if item["line"] == '4"-PG-313050'
        )
        planned = next(
            item for item in dates["2026-09-18"]["lookahead"]
            if item["line"] == '4"-PG-313050'
        )

        self.assertEqual((performed["spools"], performed["status"]), (15, "partial"))
        self.assertEqual(performed["performed_spools"], 15)
        self.assertEqual(performed["line_spools"], 16)
        self.assertEqual(performed["line_performed_spools"], 15)
        self.assertEqual(performed["line_remaining_spools"], 1)
        self.assertEqual(performed["progress_pct"], 93.8)
        self.assertEqual(performed["dates"], ["2026-08-24"])
        self.assertEqual((planned["spools"], planned["status"]), (1, "upcoming"))
        self.assertEqual(planned["remaining_spools"], 1)
        self.assertEqual(planned["progress_pct"], 93.8)
        self.assertEqual(planned["dates"], ["2026-09-18"])

    def test_every_source_row_is_visible_in_lookahead_without_mirroring_forecast(self):
        dates = fabrication_skyline(as_of_date=date(2026, 9, 3))["charts"]["dates"]

        self.assertFalse(any(not item["forecast"] and not item["lookahead"] for item in dates))
        self.assertEqual(sum(item["lookahead_total"] for item in dates), 607)
        self.assertEqual(sum(len(item["lookahead"]) for item in dates), 175)
        self.assertEqual(sum(item["performed_total"] for item in dates), 48)
        self.assertEqual(sum(item["remaining_total"] for item in dates), 559)
        september_four = next(item for item in dates if item["date"] == "2026-09-04")
        self.assertNotEqual(
            {segment["line"] for segment in september_four["forecast"]},
            {segment["line"] for segment in september_four["lookahead"]},
        )
        self.assertTrue(
            all(
                segment["status"] in {"on_time", "late", "partial", "upcoming"}
                for item in dates
                for segment in item["lookahead"]
            )
        )

    def test_cutoff_is_strict_and_statuses_advance_with_the_date(self):
        on_batch_date = fabrication_skyline(as_of_date=date(2026, 9, 14))
        next_day = fabrication_skyline(as_of_date=date(2026, 9, 15))

        self.assertEqual(on_batch_date["kpis"]["performed_spools"], 48)
        self.assertEqual(on_batch_date["kpis"]["remaining_spools"], 559)
        self.assertEqual(next_day["kpis"]["performed_spools"], 56)
        self.assertEqual(next_day["kpis"]["remaining_spools"], 551)
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
                ["MISSED", "2026-09-01", "2026-09-05", 5],
                ["UPCOMING", "2026-09-03", "2026-09-05", 6],
            ],
        }
        _, rows = skyline_source._validated_snapshot(raw)
        segments = [
            segment
            for date_bucket in skyline_source._date_segments(rows, as_of_date=date(2026, 9, 3))
            for segment in date_bucket["lookahead"]
        ]
        by_line_and_status = {
            (segment["line"], segment["status"]): segment
            for segment in segments
        }

        self.assertEqual(by_line_and_status[("PARTIAL", "partial")]["spools"], 1)
        self.assertEqual(by_line_and_status[("PARTIAL", "upcoming")]["spools"], 2)
        self.assertEqual(by_line_and_status[("LATE", "late")]["spools"], 3)
        self.assertEqual(by_line_and_status[("ON-TIME", "on_time")]["spools"], 4)
        self.assertEqual(by_line_and_status[("MISSED", "upcoming")]["spools"], 5)
        self.assertEqual(by_line_and_status[("UPCOMING", "upcoming")]["spools"], 6)

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
        self.assertEqual(payload["charts"]["dates"], [])
        self.assertEqual(payload["error"], "the source snapshot could not be read.")
        log_exception.assert_called_once()

    def test_schema_two_snapshot_is_rejected(self):
        raw = json.loads(skyline_source.SKYLINE_DATA_PATH.read_text(encoding="utf-8"))
        raw["schema"] = 2

        with self.assertRaisesRegex(ValueError, "unsupported skyline data schema"):
            skyline_source._validated_snapshot(raw)

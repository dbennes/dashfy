from copy import deepcopy
from datetime import date
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import rundown_discipline_source as source
from apps.core.rundown_source import _empty_payload, _validated_snapshot, fabrication_rundown


class RundownModeTests(SimpleTestCase):
    def fabrication_disciplines(self):
        return {
            "piping": source._piping_payload(fabrication_rundown()),
            "structural": source.structural_rundown([{
                "id": 1, "discipline": "structural", "code": "STRUCT-01", "name": "Structural scope",
                "plan_finish": date(2026, 10, 1), "source_workbook": "AVEON Schedule 1.xlsx",
                "latest_import_id": 5, "imported_at": date(2026, 9, 14),
            }]),
        }

    def test_mode_contract_preserves_real_curves_kpis_and_input(self):
        piping = fabrication_rundown()
        existing = self.fabrication_disciplines()
        before, existing_before = deepcopy(piping), deepcopy(existing)
        with patch.object(source, "rundown_disciplines_safe", return_value=existing) as loader:
            modes = source.rundown_modes_safe(piping)
        loader.assert_called_once_with(piping)
        self.assertEqual(piping, before)
        self.assertEqual(existing, existing_before)
        self.assertEqual(list(modes), ["fabrication", "installation"])
        for mode, data in modes.items():
            self.assertEqual(data["label"], mode.title())
            self.assertEqual(list(data["disciplines"]), ["piping", "electrical", "structural"])
        for discipline in ("piping", "structural"):
            actual = modes["fabrication"]["disciplines"][discipline]
            self.assertEqual(actual["charts"], existing[discipline]["charts"])
            self.assertEqual(actual["charts_json"], existing[discipline]["charts_json"])
            self.assertEqual(actual["kpis"], existing[discipline]["kpis"])
            self.assertEqual(actual["source"]["workbook"], existing[discipline]["source"]["workbook"])
            self.assertEqual(actual["source"]["data_kind"], "real")
            self.assertFalse(actual["source"]["is_sample"])

    def test_electrical_fabrication_is_unavailable_with_no_simulated_or_zero_curve(self):
        with patch.object(source, "rundown_disciplines_safe", return_value=self.fabrication_disciplines()):
            actual = source.rundown_modes_safe(fabrication_rundown())["fabrication"]["disciplines"]["electrical"]
        self.assertFalse(actual["available"])
        self.assertEqual(actual["error"], "No electrical fabrication schedule is available in DATAFY.")
        self.assertTrue(all(values == [] for values in actual["charts"].values()))
        self.assertIsNone(actual["kpis"]["scope_total"])
        self.assertFalse(actual["source"]["has_lookahead"])
        self.assertFalse(actual["source"]["is_sample"])

    def test_installation_examples_reconcile_and_differ_by_discipline(self):
        signatures = set()
        expected_scopes = {"piping": 180, "electrical": 48, "structural": 32}
        expected_variances = {"piping": 7, "electrical": 5, "structural": -8}
        for discipline in ("piping", "electrical", "structural"):
            actual = source.installation_rundown_sample(discipline)
            with self.subTest(discipline=discipline):
                self.assertTrue(actual["available"])
                self.assertEqual(actual["source"]["source_label"], "Sample data")
                self.assertEqual(actual["source"]["sample_version"], 2)
                self.assertTrue(actual["source"]["is_sample"])
                self.assertEqual(actual["source"]["data_kind"], "sample")
                self.assertEqual(actual["source"]["mode"], "installation")
                self.assertEqual(actual["source"]["workbook"], "")
                self.assertEqual(actual["kpis"]["scope_total"], expected_scopes[discipline])
                self.assertEqual(actual["kpis"]["finish_variance_days"], expected_variances[discipline])
                validated, _dates = _validated_snapshot({"schema": 1, "source": actual["source"], **actual["charts"]})
                self.assertEqual(validated["charts"], actual["charts"])
                self.assertEqual(json.loads(actual["charts_json"]), actual["charts"])
                self.assertEqual(actual["kpis"]["scope_total"], sum(value or 0 for value in actual["charts"]["baseline_total"]))
                self.assertEqual(actual["kpis"]["scope_total"], sum(value or 0 for value in actual["charts"]["lookahead_total"]))
            signatures.add(actual["charts_json"])
        self.assertEqual(len(signatures), 3)

    def test_installation_progress_is_daily_with_a_gradual_middle_peak(self):
        for discipline in ("piping", "electrical", "structural"):
            actual = source.installation_rundown_sample(discipline)
            for series in ("baseline", "lookahead"):
                with self.subTest(discipline=discipline, series=series):
                    values = actual["charts"][f"{series}_total"]
                    last_completion = max(index for index, value in enumerate(values) if value)
                    daily = values[:last_completion + 1]
                    self.assertGreaterEqual(sum(value > 0 for value in daily), len(daily) * 0.9)
                    self.assertNotIn((0, 0), list(zip(daily, daily[1:])))
                    self.assertLessEqual(max(daily), actual["kpis"]["scope_total"] * 0.1)
                    self.assertLessEqual(max(abs(right - left) for left, right in zip(daily, daily[1:])), 2)
                    middle_start = len(daily) // 2 - 3
                    middle_week = sum(daily[middle_start:middle_start + 7])
                    self.assertGreater(middle_week, sum(daily[:7]))
                    self.assertGreater(middle_week, sum(daily[-7:]))

    def test_samples_are_stable_independent_and_do_not_contact_operational_sources(self):
        with patch.object(source.real_sources, "_datafy_conn", side_effect=AssertionError("No source reads for samples")):
            first = source.installation_rundown_sample("piping")
            second = source.installation_rundown_sample("piping")
            self.assertEqual(first, second)
            first["charts"]["baseline_total"][0] = 999
            self.assertEqual(source.installation_rundown_sample("piping"), second)
            with self.assertRaises(ValueError):
                source.installation_rundown_sample("unknown")

    def test_live_source_failure_does_not_change_real_piping_or_relabel_samples(self):
        piping = fabrication_rundown()
        with patch.object(source, "rundown_disciplines", side_effect=RuntimeError("offline")), patch.object(source.logger, "exception"):
            modes = source.rundown_modes_safe(piping)
        fabrication = modes["fabrication"]["disciplines"]
        self.assertTrue(fabrication["piping"]["available"])
        self.assertEqual(fabrication["piping"]["charts"], piping["charts"])
        self.assertFalse(fabrication["structural"]["available"])
        self.assertFalse(fabrication["electrical"]["available"])
        self.assertTrue(all(row["available"] and row["source"]["is_sample"] for row in modes["installation"]["disciplines"].values()))

    def test_unavailable_ros_is_not_replaced_with_installation_samples(self):
        piping = _empty_payload("ROS is unavailable")
        with patch.object(source, "rundown_disciplines", side_effect=RuntimeError("offline")), patch.object(source.logger, "exception"):
            modes = source.rundown_modes_safe(piping)
        actual = modes["fabrication"]["disciplines"]["piping"]
        self.assertFalse(actual["available"])
        self.assertEqual(actual["error"], "ROS is unavailable")
        self.assertFalse(actual["source"]["is_sample"])
        self.assertEqual(actual["charts"]["dates"], [])

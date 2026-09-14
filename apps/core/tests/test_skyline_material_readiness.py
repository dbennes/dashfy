import json
from copy import deepcopy
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import skyline_source


class SkylineMaterialReadinessTests(SimpleTestCase):
    cutoff = date(2026, 9, 14)
    line = '4"-TEST-001'

    def snapshot(self):
        return {
            "schema": 3,
            "source": {"snapshot_date": "2026-09-02"},
            "columns": ["line", "baseline_date", "lookahead_date", "spools"],
            "rows": [
                [self.line, "2026-09-04", "2026-09-03", 2],
                [self.line, "2026-09-04", "2026-09-18", 3],
                ['6"-TEST-002', "2026-09-04", "2026-09-03", 4],
            ],
        }

    def evidence(self, status="ready", **changes):
        result = {
            "status": status,
            "source": "Synthetic test evidence",
            "as_of_date": "2026-09-14",
            "note": "Synthetic fixture; no operational confirmation.",
        }
        result.update(changes)
        return result

    def payload(self, snapshot):
        with patch.object(skyline_source, "SKYLINE_DATA_PATH") as data_path:
            data_path.read_text.return_value = json.dumps(snapshot)
            return skyline_source.fabrication_skyline(as_of_date=self.cutoff)

    def assert_unknown(self, category):
        self.assertEqual(
            category,
            {"status": "unknown", "source": "", "as_of_date": "", "note": ""},
        )

    def test_existing_snapshot_without_evidence_keeps_every_category_unknown(self):
        payload = self.payload(self.snapshot())
        readiness = payload["charts"]["material_readiness"]

        self.assertTrue(payload["available"])
        self.assertEqual(len(readiness), 2)
        # The fully performed spool line must not imply ready materials.
        self.assertEqual(payload["kpis"]["on_time_spools"], 4)
        for categories in readiness.values():
            self.assertEqual(list(categories), ["supports", "erection", "valves"])
            for category in categories.values():
                self.assert_unknown(category)

    def test_valid_categories_are_independent_and_preserve_spool_totals(self):
        raw = self.snapshot()
        before = self.payload(raw)
        raw["material_readiness"] = {
            self.line: {
                "supports": self.evidence("ready"),
                "erection": self.evidence("pending"),
                "valves": self.evidence("partial"),
            },
        }
        after = self.payload(raw)
        readiness = after["charts"]["material_readiness"]

        self.assertEqual(readiness[self.line], raw["material_readiness"][self.line])
        self.assertEqual(after["kpis"], before["kpis"])
        for key in ("dates", "status_totals", "status_line_counts"):
            self.assertEqual(after["charts"][key], before["charts"][key])
        self.assertEqual(json.loads(after["charts_json"]), after["charts"])
        segments = [
            segment
            for bucket in after["charts"]["dates"]
            for segment in bucket["lookahead"]
            if segment["line"] == self.line
        ]
        self.assertEqual(len(segments), 2)
        self.assertTrue(all(readiness[segment["line"]]["supports"]["status"] == "ready" for segment in segments))

    def test_invalid_category_does_not_hide_valid_siblings(self):
        invalid_values = [None, [], "ready", {"status": ["ready"]}, {"status": "complete"}]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                raw = self.snapshot()
                raw["material_readiness"] = {
                    self.line: {"supports": invalid, "valves": self.evidence()},
                }
                categories = self.payload(raw)["charts"]["material_readiness"][self.line]
                self.assert_unknown(categories["supports"])
                self.assert_unknown(categories["erection"])
                self.assertEqual(categories["valves"]["status"], "ready")

    def test_operational_states_require_attributable_nonfuture_evidence(self):
        invalid_evidence = [
            {"source": ""},
            {"source": "   "},
            {"source": ["Synthetic source"]},
            {"as_of_date": None},
            {"as_of_date": "2026-02-30"},
            {"as_of_date": "20260914"},
            {"as_of_date": "2026-09-15"},
        ]
        for status in ("ready", "pending", "partial", "not_applicable"):
            for changes in invalid_evidence:
                with self.subTest(status=status, changes=changes):
                    raw = self.snapshot()
                    raw["material_readiness"] = {
                        self.line: {"supports": self.evidence(status, **changes)},
                    }
                    self.assert_unknown(self.payload(raw)["charts"]["material_readiness"][self.line]["supports"])

    def test_not_applicable_is_explicit_and_unknown_can_explain_pending_source(self):
        raw = self.snapshot()
        raw["material_readiness"] = {
            self.line: {
                "supports": self.evidence("not_applicable"),
                "erection": {"status": "unknown", "note": "Awaiting erection material list."},
            },
        }
        categories = self.payload(raw)["charts"]["material_readiness"][self.line]
        self.assertEqual(categories["supports"]["status"], "not_applicable")
        self.assertEqual(categories["erection"]["status"], "unknown")
        self.assertEqual(categories["erection"]["note"], "Awaiting erection material list.")
        self.assert_unknown(categories["valves"])

    def test_only_exact_line_identifiers_receive_evidence(self):
        raw = self.snapshot()
        raw["material_readiness"] = {
            self.line + "-100-CC": {"supports": self.evidence()},
            " " + self.line: {"valves": self.evidence()},
        }
        readiness = self.payload(raw)["charts"]["material_readiness"]
        self.assertEqual(set(readiness), {self.line, '6"-TEST-002'})
        for category in readiness[self.line].values():
            self.assert_unknown(category)

    def test_invalid_optional_maps_do_not_break_the_safe_screen_payload(self):
        baseline = self.payload(self.snapshot())
        for invalid in (None, [], 7, "ready", {self.line: ["ready"]}):
            with self.subTest(invalid=invalid):
                raw = deepcopy(self.snapshot())
                raw["material_readiness"] = invalid
                with (
                    patch.object(skyline_source, "SKYLINE_DATA_PATH") as data_path,
                    patch.object(skyline_source.timezone, "localdate", return_value=self.cutoff),
                    patch.object(skyline_source.logger, "exception") as log_exception,
                ):
                    data_path.read_text.return_value = json.dumps(raw)
                    payload = skyline_source.fabrication_skyline_safe()
                self.assertTrue(payload["available"])
                self.assertEqual(payload["charts"], baseline["charts"])
                log_exception.assert_not_called()

    def test_empty_fallback_includes_the_readiness_lookup(self):
        self.assertEqual(skyline_source._empty_payload()["charts"]["material_readiness"], {})

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import rundown_discipline_source as source
from apps.core.rundown_source import fabrication_rundown


class RundownDisciplineTests(SimpleTestCase):
    def package(self, pk=1, **changes):
        row = {
            "id": pk, "code": f"FB-{pk:03}", "name": f"Structural package {pk}",
            "discipline": "structural", "document_id": pk, "weight_tons": "1.5",
            "plan_finish": date(2026, 9, 10), "actual_finish": None,
            "source_workbook": "AVEON Schedule 1.xlsx", "latest_import_id": 4,
            "imported_at": datetime(2026, 8, 21, 15, tzinfo=timezone.utc),
        }
        row.update(changes)
        return row

    def test_original_piping_scope_curves_and_kpis_are_unchanged(self):
        original = fabrication_rundown()
        before = deepcopy(original)
        piping = source._piping_payload(original)
        self.assertEqual(original, before)
        self.assertEqual(piping["charts"], original["charts"])
        self.assertEqual(piping["charts_json"], original["charts_json"])
        self.assertEqual(piping["kpis"], original["kpis"])
        self.assertEqual(piping["kpis"]["scope_total"], 607)
        self.assertEqual(piping["source"]["unit"], "spools")
        self.assertEqual(piping["source"]["workbook"], original["source"]["workbook"])
        self.assertEqual(piping["source"]["title"], "Piping ISO rundown (ROS)")
        self.assertEqual(piping["source"]["notice"], "")
        self.assertEqual(piping["source"]["source_label"], "Runddown!T1:X75 · reconciled schedule · snapshot 02 Sep 26")

    def test_structural_counts_packages_and_reconciles_daily_remaining_balance(self):
        result = source.structural_rundown([
            self.package(), self.package(2), self.package(3, plan_finish=date(2026, 9, 12)),
        ])
        charts = result["charts"]
        self.assertTrue(result["available"])
        self.assertEqual(result["source"]["unit"], "packages")
        self.assertEqual(result["kpis"]["scope_total"], 3)
        self.assertEqual(charts["dates"], ["2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13"])
        self.assertEqual(charts["baseline_total"], [2, 0, 1, 0])
        self.assertEqual(charts["baseline_rundown"], [3, 1, 1, 0])
        for index in range(1, len(charts["dates"])):
            self.assertEqual(charts["baseline_rundown"][index], charts["baseline_rundown"][index-1] - charts["baseline_total"][index-1])
        self.assertEqual(result["kpis"]["planned_finish_label"], "12 Sep 26")
        self.assertEqual(result["kpis"]["baseline_finish_label"], "13 Sep 26")
        self.assertEqual(json.loads(result["charts_json"]), charts)

    def test_lookahead_is_unavailable_rather_than_zero_or_duplicated_plan(self):
        result = source.structural_rundown([self.package(plan_finish=date(2020, 1, 1))])
        self.assertFalse(result["source"]["has_lookahead"])
        self.assertEqual(result["charts"]["lookahead_total"], [None, None])
        self.assertEqual(result["charts"]["lookahead_rundown"], [None, None])
        self.assertEqual(result["kpis"]["lookahead_finish_label"], "—")
        self.assertIsNone(result["kpis"]["finish_variance_days"])

    def test_missing_date_stays_in_denominator_and_does_not_create_false_zero(self):
        result = source.structural_rundown([self.package(), self.package(2, plan_finish=None)])
        self.assertEqual(result["kpis"]["scope_total"], 2)
        self.assertEqual(result["kpis"]["scheduled_scope"], 1)
        self.assertEqual(result["kpis"]["unscheduled_scope"], 1)
        self.assertEqual(result["charts"]["baseline_rundown"], [2, 1])
        self.assertEqual(result["kpis"]["baseline_finish_label"], "—")
        self.assertEqual(result["source"]["unscheduled_packages"][0]["package_id"], 2)

    def test_packages_without_drawing_links_still_belong_to_scheduled_scope(self):
        result = source.structural_rundown([self.package(document_id=None)])
        self.assertEqual(result["kpis"]["scope_total"], 1)
        self.assertEqual(result["kpis"]["scheduled_scope"], 1)

    def test_incomplete_weights_and_shared_drawings_do_not_become_fake_tonnage(self):
        result = source.structural_rundown([
            self.package(weight_tons="13.187"),
            self.package(2, document_id=1, weight_tons="13.187"),
            self.package(3, weight_tons=None),
        ])
        self.assertEqual(result["source"]["unit"], "packages")
        self.assertEqual(result["kpis"]["scope_total"], 3)
        self.assertEqual(result["kpis"]["missing_weight_count"], 1)
        self.assertEqual(result["kpis"]["duplicate_drawing_package_count"], 2)
        self.assertEqual(result["charts"]["baseline_total"], [3, 0])

    def test_piping_or_other_packages_do_not_leak_into_structural(self):
        result = source.structural_rundown([
            self.package(), self.package(2, discipline="piping"), self.package(3, discipline="other"),
        ])
        self.assertEqual(result["kpis"]["scope_total"], 1)

    def test_duplicate_source_rows_are_not_counted_twice(self):
        package = self.package()
        result = source.structural_rundown([package, deepcopy(package)])
        self.assertEqual(result["kpis"]["scope_total"], 1)
        with self.assertRaises(ValueError):
            source.structural_rundown([package, self.package(plan_finish=date(2026, 9, 12))])

    def test_unattributable_dates_are_not_scheduled(self):
        result = source.structural_rundown([self.package(source_workbook="")])
        self.assertFalse(result["available"])
        self.assertEqual(result["charts"]["dates"], [])
        self.assertEqual(result["kpis"]["scope_total"], 1)
        self.assertEqual(result["kpis"]["unscheduled_scope"], 1)

    def test_import_provenance_uses_the_linked_schedule_timestamp(self):
        result = source.structural_rundown([self.package()])
        self.assertEqual(result["source"]["workbook"], "AVEON Schedule 1.xlsx")
        self.assertEqual(result["source"]["snapshot_date"], "2026-08-21")
        self.assertEqual(result["source"]["snapshot_label"], "21 Aug 26")
        self.assertEqual(result["source"]["import_ids"], [4])

    def test_other_attributable_schedule_is_not_mislabeled_as_aveon(self):
        result = source.structural_rundown([self.package(source_workbook="Contractor schedule.xlsx")])
        self.assertTrue(result["available"])
        self.assertEqual(result["source"]["workbook"], "Contractor schedule.xlsx")
        self.assertNotIn("AVEON", result["source"]["source_label"])
        self.assertNotIn("AVEON", result["source"]["baseline_label"])
        self.assertNotIn("AVEON", result["source"]["notice"])

    def test_structural_source_failure_leaves_the_original_piping_view_available(self):
        piping = fabrication_rundown()
        with patch.object(source, "rundown_disciplines", side_effect=RuntimeError("offline")), patch.object(source.logger, "exception"):
            result = source.rundown_disciplines_safe(piping)
        self.assertEqual(list(result), ["piping", "structural"])
        self.assertTrue(result["piping"]["available"])
        self.assertEqual(result["piping"]["charts_json"], piping["charts_json"])
        self.assertFalse(result["structural"]["available"])
        self.assertIn("could not be refreshed", result["structural"]["error"])

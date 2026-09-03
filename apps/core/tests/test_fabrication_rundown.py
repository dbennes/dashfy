from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.rundown_source import fabrication_rundown, fabrication_rundown_safe


class FabricationRundownSnapshotTests(SimpleTestCase):
    def test_snapshot_matches_the_runddown_t_to_x_range(self):
        payload = fabrication_rundown()
        charts = payload["charts"]

        self.assertTrue(payload["available"])
        self.assertEqual(payload["source"]["worksheet"], "Runddown")
        self.assertEqual(payload["source"]["range"], "T1:X75")
        self.assertEqual(payload["source"]["snapshot_date"], "2026-09-02")
        self.assertEqual(charts["dates"][0], "2026-08-21")
        self.assertEqual(charts["dates"][-1], "2026-12-11")
        self.assertTrue(all(len(values) == 74 for values in charts.values()))

        self.assertEqual(sum(charts["lookahead_total"]), 607)
        self.assertEqual(sum(value or 0 for value in charts["baseline_total"]), 607)
        self.assertEqual(charts["lookahead_rundown"][0], 607)
        self.assertEqual(charts["lookahead_rundown"][-1], 0)

    def test_rundown_balances_reconcile_with_the_previous_daily_bucket(self):
        charts = fabrication_rundown()["charts"]

        for index in range(1, len(charts["dates"])):
            self.assertEqual(
                charts["lookahead_rundown"][index],
                charts["lookahead_rundown"][index - 1]
                - charts["lookahead_total"][index - 1],
            )

        for index in range(1, len(charts["dates"])):
            current = charts["baseline_rundown"][index]
            if current is None:
                break
            self.assertEqual(
                current,
                charts["baseline_rundown"][index - 1]
                - charts["baseline_total"][index - 1],
            )

    def test_baseline_zero_is_preserved_before_the_trailing_blanks(self):
        payload = fabrication_rundown()
        charts = payload["charts"]
        finish_index = charts["dates"].index("2026-11-26")

        self.assertEqual(charts["baseline_rundown"][finish_index], 0)
        self.assertTrue(all(value is None for value in charts["baseline_rundown"][finish_index + 1:]))
        self.assertEqual(payload["kpis"]["baseline_finish_label"], "26 Nov 26")
        self.assertEqual(payload["kpis"]["lookahead_finish_label"], "11 Dec 26")
        self.assertEqual(payload["kpis"]["finish_variance_days"], 15)

    def test_safe_loader_degrades_without_breaking_s03(self):
        missing = Path("definitely-missing-fabrication-rundown.json")
        with (
            patch("apps.core.rundown_source.RUNDOWN_DATA_PATH", missing),
            patch("apps.core.rundown_source.logger.exception") as log_exception,
        ):
            payload = fabrication_rundown_safe()

        self.assertFalse(payload["available"])
        self.assertEqual(payload["charts"]["dates"], [])
        self.assertEqual(payload["error"], "the source snapshot could not be read.")
        log_exception.assert_called_once()

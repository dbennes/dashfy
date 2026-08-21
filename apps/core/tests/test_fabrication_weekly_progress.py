from decimal import Decimal

from django.test import SimpleTestCase

from apps.core.fabrication_source import (
    overall_pct,
    overall_value,
    stage_is_applicable,
    stage_value,
)


class FabricationWeeklyProgressCompatibilityTests(SimpleTestCase):
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

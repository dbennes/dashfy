"""The existing cockpit must carry live material evidence into its skyline."""
import json
import re
from contextlib import ExitStack
from copy import deepcopy
from datetime import date
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.models import User
from apps.core import rundown_source, skyline_source
from apps.core.views import home_view


@override_settings(DASHFY_SHOW_TRACKING=False)
class SkylineLiveHomeTests(SimpleTestCase):
    cutoff = date(2026, 9, 14)

    def setUp(self):
        self.enterContext(patch(
            "apps.core.views.ros_workbook.load_current_schedule",
            return_value={
                "skyline": json.loads(skyline_source.SKYLINE_DATA_PATH.read_text(encoding="utf-8")),
                "rundown": json.loads(rundown_source.RUNDOWN_DATA_PATH.read_text(encoding="utf-8")),
                "batch": None,
            },
        ))
        # Keep the real versioned schedule; the live map is deliberately absent
        # from it, so this test catches a missing view-to-integration connection.
        self.schedule = skyline_source.fabrication_skyline(as_of_date=self.cutoff)
        self.lines = sorted(self.schedule["charts"]["material_readiness"])
        self.line = self.lines[0]
        self.request = RequestFactory().get("/")
        self.request.user = User(username="unsaved-skyline-test", role=User.Role.ADMIN)
        self.request.session = {}
        self.mocks = self.enterContext(ExitStack())
        self.mocks.enter_context(
            patch("apps.core.views.Announcement.objects.filter", return_value=[])
        )
        users = self.mocks.enter_context(patch("apps.core.views.User.objects.filter"))
        users.return_value.count.return_value = 0
        self.mocks.enter_context(
            patch("apps.core.views.real_sources.management_dashboard", return_value={})
        )
        self.mocks.enter_context(
            patch(
                "apps.core.views.fabrication_source.fabrication_progress_safe",
                return_value={"available": False, "charts": {}, "stages": []},
            )
        )
        self.mocks.enter_context(
            patch.object(skyline_source.timezone, "localdate", return_value=self.cutoff)
        )
        self.aveon_loader = self.mocks.enter_context(
            patch(
                "apps.core.skyline_aveon_source.aveon_skyline_safe",
                return_value=skyline_source._empty_payload("AVEON test source unavailable"),
            )
        )
        self.mocks.enter_context(
            patch(
                "apps.core.rundown_discipline_source.rundown_disciplines_safe",
                side_effect=lambda piping_payload: {
                    "piping": piping_payload,
                    "structural": rundown_source._empty_payload("Structural test source unavailable"),
                },
            )
        )

    def rendered_payloads(self):
        response = home_view(self.request)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="s03"', html)
        self.assertIn('id="fabSkylinePlot"', html)
        payloads = {}
        for script_id in ("fabSkylineData", "fabSkylineSchedules"):
            match = re.search(
                rf'<script id="{script_id}" type="application/json">(.*?)</script>',
                html,
                re.DOTALL,
            )
            self.assertIsNotNone(match, f"The cockpit must render {script_id}.")
            payloads[script_id] = json.loads(match.group(1))
        return payloads

    def rendered_charts(self):
        return self.rendered_payloads()["fabSkylineData"]

    def assert_schedule_preserved(self, charts):
        for key in ("dates", "status_totals", "status_line_counts"):
            self.assertEqual(charts[key], self.schedule["charts"][key])

    @patch("apps.core.skyline_material_source.skyline_material_readiness")
    def test_existing_home_renders_three_live_material_states(self, live_readiness):
        counts_by_category = {
            "supports": {
                "total_items": 4, "ready_items": 4, "received_items": 4,
                "pending_items": 0, "fully_po_allocated_items": 4,
            },
            "erection": {
                "total_items": 4, "ready_items": 2, "received_items": 2,
                "pending_items": 2, "fully_po_allocated_items": 3,
            },
            # Full PO allocation is independent of physical availability.
            "valves": {
                "total_items": 3, "ready_items": 0, "received_items": 0,
                "pending_items": 3, "fully_po_allocated_items": 3,
            },
        }
        live_categories = {
            category: {
                "status": status,
                "source": "DATAFY/SPDM test integration",
                "as_of_date": self.cutoff.isoformat(),
                "note": "Synthetic live-loader response; no operational fixture write.",
                "counts": counts_by_category[category],
            }
            for category, status in (
                ("supports", "ready"),
                ("erection", "partial"),
                ("valves", "pending"),
            )
        }
        # Operational notes can contain markup-like text. It must remain data
        # in the existing page's JSON script rather than terminate that script.
        live_categories["valves"]["note"] = 'Reference </script><b>V-001 & V-002</b>'
        live_readiness.return_value = {self.line: live_categories}

        charts = self.rendered_charts()

        live_readiness.assert_called_once()
        call = live_readiness.call_args
        self.assertEqual(sorted(call.args[0]), self.lines)
        self.assertEqual(call.kwargs["as_of_date"], self.cutoff)
        self.assertEqual(charts["material_readiness"][self.line], live_categories)
        self.assert_schedule_preserved(charts)
        self.assertIsNone(self.request.user.pk)

    @patch(
        "apps.core.skyline_material_source.skyline_material_readiness",
        side_effect=RuntimeError("DATAFY test source unavailable"),
    )
    def test_live_source_outage_preserves_home_and_schedule(self, live_readiness):
        with patch.object(skyline_source.logger, "exception"):
            charts = self.rendered_charts()

        live_readiness.assert_called_once()
        self.assert_schedule_preserved(charts)
        self.assertEqual(sorted(charts["material_readiness"]), self.lines)
        for categories in charts["material_readiness"].values():
            self.assertEqual(set(categories), {"supports", "erection", "valves"})
            for evidence in categories.values():
                self.assertEqual(evidence["status"], "unknown")
                self.assertTrue(evidence["note"])

    @patch("apps.core.skyline_material_source.skyline_material_readiness", return_value={})
    def test_home_keeps_aveon_plan_distinct_from_ros_and_confirmed_actuals(self, _live_readiness):
        planned_date = "2027-01-08"
        aveon = skyline_source._empty_payload()
        aveon.update(available=True)
        aveon["source"] = {
            "mode": "aveon",
            "as_of_date": self.cutoff.isoformat(),
            "source_label": "Synthetic AVEON fabrication plan",
        }
        aveon["kpis"].update(
            line_count=2, scope_spools=3, remaining_line_count=2,
            remaining_spools=3, scheduled_line_count=1, scheduled_spools=2,
            unmapped_line_count=1, unmapped_spools=1,
            confirmed_actual_line_count=0, confirmed_actual_spools=0,
        )
        aveon["charts"]["dates"] = [{
            "date": planned_date,
            "forecast_total": 2,
            "lookahead_total": 0,
            "performed_total": 0,
            "remaining_total": 2,
            "forecast": [{
                "line": self.line, "date": planned_date,
                "dates": [planned_date], "spools": 2, "date_kind": "planned",
                "actual_date_confirmed": False,
            }],
            "lookahead": [],
        }]
        aveon["charts"]["unmapped"] = [{
            "line": self.lines[1], "spools": 1,
            "reason": "No matching active AVEON fabrication package.",
        }]
        # Source options must share the material map already shipped in the
        # main skyline payload instead of copying it into each schedule.
        aveon["charts"]["material_readiness"] = {self.line: {"sentinel": "not duplicated"}}
        aveon["charts_json"] = json.dumps(aveon["charts"])
        self.aveon_loader.return_value = deepcopy(aveon)

        payloads = self.rendered_payloads()

        self.aveon_loader.assert_called_once()
        self.assert_schedule_preserved(self.aveon_loader.call_args.args[0]["charts"])
        self.assert_schedule_preserved(payloads["fabSkylineData"])
        schedules = payloads["fabSkylineSchedules"]
        self.assertEqual(set(schedules), {"ros", "aveon"})
        self.assertTrue(schedules["ros"]["available"])
        self.assertEqual(schedules["ros"]["kpis"], self.schedule["kpis"])
        actual_aveon = schedules["aveon"]
        self.assertTrue(actual_aveon["available"])
        self.assertEqual(actual_aveon["source"], aveon["source"])
        self.assertEqual(actual_aveon["kpis"], aveon["kpis"])
        self.assertEqual(actual_aveon["charts"]["dates"], aveon["charts"]["dates"])
        self.assertNotIn(planned_date, {bucket["date"] for bucket in payloads["fabSkylineData"]["dates"]})
        self.assertEqual(actual_aveon["charts"]["unmapped"], aveon["charts"]["unmapped"])
        self.assertEqual(actual_aveon["kpis"]["performed_spools"], 0)
        self.assertNotIn("charts_json", actual_aveon)
        self.assertNotIn("material_readiness", actual_aveon["charts"])

    @patch("apps.core.skyline_material_source.skyline_material_readiness", return_value={})
    def test_aveon_outage_is_not_replaced_with_ros_dates(self, _live_readiness):
        payloads = self.rendered_payloads()

        self.aveon_loader.assert_called_once()
        self.assert_schedule_preserved(payloads["fabSkylineData"])
        schedules = payloads["fabSkylineSchedules"]
        self.assertTrue(schedules["ros"]["available"])
        self.assertFalse(schedules["aveon"]["available"])
        self.assertEqual(schedules["aveon"]["error"], "AVEON test source unavailable")
        self.assertEqual(schedules["aveon"]["charts"]["dates"], [])

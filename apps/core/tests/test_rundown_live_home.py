"""Discipline rundown data reaches the existing cockpit without mixing scopes."""
import json
import re
from copy import deepcopy
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.models import User
from apps.core import rundown_source, skyline_source
from apps.core.views import home_view


@override_settings(DASHFY_SHOW_TRACKING=False)
class RundownLiveHomeTests(SimpleTestCase):
    def setUp(self):
        self.piping = rundown_source.fabrication_rundown()
        self.disciplines = {
            "piping": deepcopy(self.piping),
            "structural": rundown_source._empty_payload("Structural test source unavailable"),
        }
        self.disciplines["piping"]["source"].update(
            discipline="piping", discipline_label="Piping", unit="spools",
            unit_label="spools", baseline_label="Baseline", lookahead_label="Lookahead",
            has_lookahead=True,
        )
        self.disciplines["structural"]["source"].update(
            discipline="structural", discipline_label="Structural", unit="packages",
            unit_label="packages", baseline_label="AVEON plan", lookahead_label="Lookahead",
            has_lookahead=False,
        )
        self.request = RequestFactory().get("/")
        self.request.user = User(username="unsaved-rundown-test", role=User.Role.ADMIN)
        self.request.session = {}
        self.enterContext(patch("apps.core.views.Announcement.objects.filter", return_value=[]))
        users = self.enterContext(patch("apps.core.views.User.objects.filter"))
        users.return_value.count.return_value = 0
        self.enterContext(patch("apps.core.views.real_sources.management_dashboard", return_value={}))
        self.enterContext(patch(
            "apps.core.views.fabrication_source.fabrication_progress_safe",
            return_value={"available": False, "charts": {}, "stages": []},
        ))
        # Isolate unrelated live skyline integrations while rendering the real
        # home and its existing rundown snapshot, with no stored login user.
        self.enterContext(patch(
            "apps.core.skyline_source.fabrication_skyline_safe",
            return_value=skyline_source._empty_payload(),
        ))
        self.enterContext(patch(
            "apps.core.skyline_aveon_source.aveon_skyline_safe",
            return_value=skyline_source._empty_payload(),
        ))
        self.loader = self.enterContext(patch(
            "apps.core.rundown_discipline_source.rundown_disciplines_safe",
            return_value=self.disciplines,
        ))

    def rendered_home(self):
        response = home_view(self.request)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="s03"', html)
        self.assertIn('id="fabRundownChart"', html)
        match = re.search(
            r'<script id="fabRundownDisciplines" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "The home must ship the rundown discipline payload.")
        return html, json.loads(match.group(1))

    def assert_piping_preserved(self, actual):
        self.assertTrue(actual["available"])
        self.assertEqual(actual["charts"], self.piping["charts"])
        self.assertEqual(actual["kpis"], self.piping["kpis"])
        self.assertEqual(actual["kpis"]["scope_total"], 607)

    def test_top_selector_defaults_to_the_original_piping_rundown(self):
        html, disciplines = self.rendered_home()

        self.loader.assert_called_once()
        self.assert_piping_preserved(self.loader.call_args.args[0])
        self.assert_piping_preserved(disciplines["piping"])
        selector = re.search(
            r'<select\b[^>]*\bid="fabRundownDiscipline"[^>]*>(.*?)</select>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(selector, "Discipline must be selectable above the chart.")
        self.assertLess(selector.start(), html.index('id="fabRundownChart"'))
        options = re.findall(r'<option\b([^>]*)>(.*?)</option>', selector.group(1), re.DOTALL)
        values = [re.search(r'value="([^"]+)"', attributes).group(1) for attributes, _ in options]
        self.assertEqual(values, ["piping", "structural"])
        selected = [value for value, (attributes, _) in zip(values, options) if re.search(r'\bselected\b', attributes)]
        self.assertEqual(selected or values[:1], ["piping"])
        self.assertIsNone(self.request.user.pk)

    def test_structural_plan_keeps_its_own_units_dates_and_safe_source_text(self):
        structural = self.disciplines["structural"]
        structural.update(available=True, error="")
        source_note = 'AVEON test import </script><b>STRUCTURE & SUPPORTS</b>'
        structural["source"].update(
            source_label=source_note, snapshot_date="2026-09-14",
            notice="Planned package finish only; no confirmed actual or lookahead dates.",
        )
        structural["kpis"].update(
            scope_total=2, scheduled_scope=2, unscheduled_scope=0, package_count=2,
            baseline_finish_label="09 Jan 27", lookahead_finish_label="—",
            finish_variance_days=None,
        )
        structural["charts"] = {
            "dates": ["2027-01-08", "2027-01-09"],
            "baseline_total": [2, 0], "baseline_rundown": [2, 0],
            "lookahead_total": [None, None], "lookahead_rundown": [None, None],
        }
        structural["charts_json"] = json.dumps(structural["charts"])

        html, disciplines = self.rendered_home()

        self.assert_piping_preserved(disciplines["piping"])
        actual = disciplines["structural"]
        self.assertEqual(actual["source"], structural["source"])
        self.assertEqual(actual["source"]["unit"], "packages")
        self.assertEqual(disciplines["piping"]["source"]["unit"], "spools")
        self.assertEqual(actual["kpis"], structural["kpis"])
        self.assertEqual(actual["charts"], structural["charts"])
        self.assertNotEqual(actual["charts"]["dates"], disciplines["piping"]["charts"]["dates"])
        self.assertFalse(actual["source"]["has_lookahead"])
        self.assertIsNone(actual["kpis"]["finish_variance_days"])
        self.assertNotIn(source_note, html)

    def test_structural_unavailable_does_not_replace_or_hide_piping(self):
        _, disciplines = self.rendered_home()

        self.assert_piping_preserved(disciplines["piping"])
        structural = disciplines["structural"]
        self.assertFalse(structural["available"])
        self.assertEqual(structural["error"], "Structural test source unavailable")
        self.assertEqual(structural["charts"]["dates"], [])
        self.assertFalse(structural["source"]["has_lookahead"])

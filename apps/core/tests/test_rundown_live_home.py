"""Discipline rundown data reaches the existing cockpit without mixing scopes."""
import json
import re
from copy import deepcopy
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.models import User
from apps.core import rundown_source, skyline_source
from apps.core.tests.test_rundown_modes_ui import rundown_modes_fixture
from apps.core.views import home_view


@override_settings(DASHFY_SHOW_TRACKING=False)
class RundownLiveHomeTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch(
            "apps.core.views.ros_workbook.load_current_schedule",
            return_value={
                "skyline": json.loads(skyline_source.SKYLINE_DATA_PATH.read_text(encoding="utf-8")),
                "rundown": json.loads(rundown_source.RUNDOWN_DATA_PATH.read_text(encoding="utf-8")),
                "batch": None,
            },
        ))
        self.piping = rundown_source.fabrication_rundown()
        self.modes = rundown_modes_fixture()
        self.disciplines = self.modes["fabrication"]["disciplines"]
        self.disciplines["piping"] = deepcopy(self.piping)
        self.disciplines["structural"] = rundown_source._empty_payload("Structural test source unavailable")
        self.disciplines["piping"]["source"].update(
            discipline="piping", discipline_label="Piping", unit="spools",
            unit_label="spools", baseline_label="Baseline", lookahead_label="Lookahead",
            has_lookahead=True, mode="fabrication", mode_label="Fabrication",
            data_kind="real", is_sample=False,
        )
        self.disciplines["structural"]["source"].update(
            discipline="structural", discipline_label="Structural", unit="packages",
            unit_label="packages", baseline_label="AVEON plan", lookahead_label="Lookahead",
            has_lookahead=False, mode="fabrication", mode_label="Fabrication",
            data_kind="real", is_sample=False,
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
        self.enterContext(patch("apps.core.views.rundown_workbook.overlay_modes", side_effect=lambda modes: modes))
        self.loader = self.enterContext(patch(
            "apps.core.rundown_discipline_source.rundown_modes_safe",
            return_value=self.modes,
        ))

    def rendered_home(self):
        response = home_view(self.request)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="s03"', html)
        self.assertIn('id="fabRundownChart"', html)
        match = re.search(
            r'<script id="fabRundownModes" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "The home must ship both rundown modes and their discipline payloads.")
        return html, json.loads(match.group(1))

    def assert_piping_preserved(self, actual):
        self.assertTrue(actual["available"])
        self.assertEqual(actual["charts"], self.piping["charts"])
        self.assertEqual(actual["kpis"], self.piping["kpis"])
        self.assertEqual(actual["kpis"]["scope_total"], 607)

    def test_top_selector_defaults_to_the_original_piping_rundown(self):
        html, modes = self.rendered_home()
        disciplines = modes["fabrication"]["disciplines"]

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
        self.assertEqual(values, ["piping", "electrical", "structural"])
        selected = [value for value, (attributes, _) in zip(values, options) if re.search(r'\bselected\b', attributes)]
        self.assertEqual(selected or values[:1], ["piping"])
        buttons = re.findall(r'<button\b([^>]*\bdata-rundown-mode="[^"]+"[^>]*)>(.*?)</button>', html, re.DOTALL)
        self.assertEqual(len(buttons), 2)
        for (attributes, label), mode, pressed in zip(buttons, ("fabrication", "installation"), ("true", "false")):
            self.assertIn('data-rundown-mode="' + mode + '"', attributes)
            self.assertIn('aria-pressed="' + pressed + '"', attributes)
            self.assertIn('aria-controls="fabRundownChart fabRundownSummary"', attributes)
            self.assertEqual(label.strip(), mode.title())
            self.assertLess(html.index('data-rundown-mode="' + mode + '"'), selector.start())
        self.assertRegex(html, r'<span\b[^>]*id="fabRundownSample"[^>]*\bhidden[^>]*>Sample data</span>')
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

        html, modes = self.rendered_home()
        disciplines = modes["fabrication"]["disciplines"]

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
        _, modes = self.rendered_home()
        disciplines = modes["fabrication"]["disciplines"]

        self.assert_piping_preserved(disciplines["piping"])
        structural = disciplines["structural"]
        self.assertFalse(structural["available"])
        self.assertEqual(structural["error"], "Structural test source unavailable")
        self.assertEqual(structural["charts"]["dates"], [])
        self.assertFalse(structural["source"]["has_lookahead"])

    def test_installation_samples_and_missing_electrical_source_remain_distinct(self):
        original = deepcopy(self.modes)
        html, modes = self.rendered_home()

        self.assertEqual(set(modes), {"fabrication", "installation"})
        self.assertEqual(modes["fabrication"]["label"], "Fabrication")
        self.assertEqual(modes["installation"]["label"], "Installation")
        self.assert_piping_preserved(modes["fabrication"]["disciplines"]["piping"])
        electrical = modes["fabrication"]["disciplines"]["electrical"]
        self.assertFalse(electrical["available"])
        self.assertFalse(electrical["source"]["is_sample"])
        self.assertEqual(electrical["source"]["data_kind"], "real")
        self.assertEqual(electrical["charts"]["dates"], [])
        for key, sample in modes["installation"]["disciplines"].items():
            self.assertTrue(sample["available"], key)
            self.assertTrue(sample["source"]["is_sample"], key)
            self.assertEqual(sample["source"]["data_kind"], "sample")
            self.assertEqual(sample["source"]["source_label"], "Sample data")
            self.assertEqual(sample["source"]["mode"], "installation")
            self.assertEqual(sample["source"]["discipline"], key)
            self.assertIn("demonstration", sample["source"]["notice"])
        self.assertEqual(self.modes, original, "Rendering must not alter either source payload")
        # The other card retains its own source controls and data contract.
        self.assertIn('data-fab-skyline', html)
        self.assertIn('data-skyline-schedule="ros"', html)
        self.assertIn('data-skyline-schedule="aveon"', html)
        self.assertIn('id="fabSkylineSchedules"', html)

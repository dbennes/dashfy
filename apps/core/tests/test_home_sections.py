import re
from pathlib import Path
from unittest.mock import patch

from datetime import date

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class FabricationRundownStyleTests(SimpleTestCase):
    def test_rundown_has_compact_summary_legend_and_responsive_canvas(self):
        css_path = Path(__file__).resolve().parents[3] / "static" / "css" / "fabrication-s03.css"
        css = css_path.read_text(encoding="utf-8")

        def rule(selector):
            match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.DOTALL)
            self.assertIsNotNone(match, f"missing CSS rule: {selector}")
            return match.group(1)

        card = rule(".cockpit-v3 #s03 .fab-rundown-card")
        head = rule(".cockpit-v3 #s03 [data-fab-rundown] .fab-rundown-head")
        kpis = rule(".cockpit-v3 #s03 .fab-rundown-kpis")
        legend = rule(".cockpit-v3 #s03 .fab-rundown-legend")
        chart = rule(".cockpit-v3 #s03 .fab-rundown-chart")
        canvas = rule(".cockpit-v3 #s03 .fab-rundown-canvas")

        self.assertIn("height: 432px", card)
        self.assertIn("min-height: 0", card)
        self.assertIn("align-items: center", head)
        self.assertIn("grid-template-columns: repeat(4", kpis)
        self.assertIn("background: var(--fb-bg-subtle)", kpis)
        self.assertIn("justify-content: flex-end", legend)
        self.assertIn("min-height: 30px", legend)
        self.assertIn("border-bottom: 1px solid var(--fb-border-subtle)", legend)
        self.assertIn("min-height: 0", chart)
        self.assertIn("min-height: 0", canvas)
        self.assertIn("height: 100% !important", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn("min-height: 240px", css)


class FabricationSkylineStyleTests(SimpleTestCase):
    def test_skyline_uses_one_column_per_period_without_internal_scroll(self):
        css_path = Path(__file__).resolve().parents[3] / "static" / "css" / "fabrication-s03.css"
        css = css_path.read_text(encoding="utf-8")

        def rule(selector):
            match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.DOTALL)
            self.assertIsNotNone(match, f"missing CSS rule: {selector}")
            return match.group(1)

        viewport = rule(".cockpit-v3 #s03 .fab-skyline-viewport")
        card = rule(".cockpit-v3 #s03 .fab-skyline-card")
        head = rule(".cockpit-v3 #s03 .fab-skyline-head")
        legend = rule(".cockpit-v3 #s03 .fab-skyline-legend")
        partial_legend = rule(".cockpit-v3 #s03 .fab-skyline-legend .is-partial")
        plot = rule(".cockpit-v3 #s03 .fab-skyline-plot")
        labels = rule(".cockpit-v3 #s03 .fab-skyline-band-labels")
        matrix = rule(".cockpit-v3 #s03 .fab-skyline-matrix")
        date_column = rule(".cockpit-v3 #s03 .fab-skyline-date-column")
        half = rule(".cockpit-v3 #s03 .fab-skyline-half")
        grid = rule(".cockpit-v3 #s03 .fab-skyline-half::before")
        lookahead_grid = rule(".cockpit-v3 #s03 .fab-skyline-half.is-lookahead::before")
        total = rule(".cockpit-v3 #s03 .fab-skyline-total")
        stack = rule(".cockpit-v3 #s03 .fab-skyline-stack")
        item = rule(".cockpit-v3 #s03 .fab-skyline-item")

        self.assertIn("overflow: hidden", viewport)
        self.assertNotIn("overflow-x: auto", viewport)
        self.assertIn("background: var(--fb-bg-elev)", card)
        self.assertNotIn("linear-gradient", card)
        self.assertIn("background: var(--fb-bg-elev)", head)
        self.assertIn("grid-template-rows: var(--fab-skyline-legend-height) auto", plot)
        self.assertIn("grid-column: 2", legend)
        self.assertIn("grid-row: 1", legend)
        self.assertIn("justify-self: end", legend)
        self.assertIn("flex-wrap: nowrap", legend)
        self.assertIn("background: transparent", legend)
        self.assertNotIn("linear-gradient", partial_legend)
        self.assertIn("#f97316", partial_legend)
        self.assertIn("var(--fb-info)", rule(".cockpit-v3 #s03 .fab-skyline-item.is-late"))
        self.assertIn("var(--fb-success)", rule(".cockpit-v3 #s03 .fab-skyline-item.is-on-time"))
        self.assertIn("grid-column: 1", labels)
        self.assertIn("grid-row: 2", labels)
        self.assertIn("grid-column: 2", viewport)
        self.assertIn("grid-row: 2", viewport)
        self.assertIn("width: 100%", matrix)
        self.assertIn("min-width: 0", matrix)
        self.assertIn("display: grid", matrix)
        self.assertIn("repeat(var(--fab-skyline-date-count), minmax(0, 1fr))", matrix)
        self.assertNotIn(".fab-skyline-matrix::before", css)
        self.assertIn("repeating-linear-gradient", grid)
        self.assertIn("to top", grid)
        self.assertIn("transparent 0 15px", grid)
        self.assertIn("15px 16px", grid)
        self.assertIn("#000 0 3px, transparent 3px 8px", grid)
        self.assertIn("inset: 0 3px 2px", grid)
        self.assertIn("var(--fb-fg-faint) 40%", grid)
        self.assertIn("opacity: .64", grid)
        self.assertIn("pointer-events: none", grid)
        self.assertIn("z-index: 0", grid)
        self.assertIn("to bottom", lookahead_grid)
        self.assertIn("inset: 2px 3px 0", lookahead_grid)
        self.assertIn("border-right: 1px dashed", date_column)
        self.assertIn("position: relative", half)
        self.assertIn("isolation: isolate", half)
        self.assertIn("background: transparent", half)
        self.assertIn("z-index: 1", total)
        self.assertIn("z-index: 1", stack)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", stack)
        self.assertIn("grid-auto-flow: row", stack)
        self.assertIn("grid-auto-rows: 15px", stack)
        self.assertIn("height: 15px", item)
        self.assertIn("position: relative", item)
        self.assertIn("z-index: 1", item)
        self.assertIn("--fab-skyline-fill", item)
        self.assertIn(".fab-skyline-item.is-on-time", css)
        self.assertIn(".fab-skyline-item.is-late", css)
        self.assertIn(".fab-skyline-item.is-partial", css)
        self.assertIn(".fab-skyline-item.is-upcoming", css)
        self.assertIn("--fab-skyline-lookahead-height", css)
        self.assertNotIn("--fab-skyline-actual-height", css)
        self.assertNotIn("is-lookahead-only", css)


class HomeSectionLayoutTests(TestCase):
    """A home mantem Tracking oculto ate sua liberacao explicita."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="cockpit-tester",
            email="cockpit@example.com",
            password="cockpit-pass-123",
        )
        self.client.force_login(self.user)

    @override_settings(DASHFY_SHOW_TRACKING=False)
    @patch("apps.core.views.tracking_source.tracking_dashboard_safe")
    def test_home_exposes_fabrication_and_model_without_tracking(self, tracking_safe):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        tracking_safe.assert_not_called()
        self.assertIs(response.context["show_tracking"], False)
        self.assertIsNone(response.context["tracking"])
        self.assertIn('id="s03"', html)
        self.assertIn("S03 · Engineering · Fabrication", html)
        self.assertIn("<em>Fabrication</em> progress", html)
        self.assertNotIn('id="s04"', html)
        self.assertNotIn('data-target="s04"', html)
        self.assertNotIn("Container shipments · Trackfy", html)
        self.assertNotIn("trkInit", html)
        self.assertIn('id="s05"', html)
        self.assertIn("S05 · 3D Model", html)
        self.assertNotIn("S04 · 3D Model", html)

    @override_settings(DASHFY_SHOW_TRACKING=True)
    @patch("apps.core.views.tracking_source.tracking_dashboard_safe")
    def test_tracking_section_reads_taskfy_and_ships_charts(self, tracking_safe):
        """A S04 vem do banco do Taskfy (read-only) com os graficos do cockpit."""
        tracking_safe.return_value = {
            "available": True,
            "kpis": {},
            "charts": {},
            "charts_json": "{}",
            "open_shipments": [],
            "recent_received": [],
            "recent_issues": [],
        }
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        tracking_safe.assert_called_once_with()
        self.assertIs(response.context["show_tracking"], True)
        tracking = response.context["tracking"]
        self.assertIn("available", tracking)
        self.assertIn("kpis", tracking)
        self.assertIn("charts", tracking)
        self.assertIn('data-target="s04"', html)
        self.assertIn('id="s04"', html)
        self.assertIn('id="trkChartsData"', html)
        self.assertIn("trkInit", html)
        for canvas_id in ("trkFlowChart", "trkItemsChart", "trkFleetChart"):
            self.assertIn(f'id="{canvas_id}"', html)

    def test_fabrication_section_ships_its_own_scoped_stylesheet(self):
        """A S03 e uma ilha visual: precisa da folha propria e do Chart.js."""
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        self.assertIn("css/fabrication-s03.css", html)
        self.assertIn("chart.js@4.4.1", html)

    def test_fabrication_section_has_the_three_charts_and_the_table(self):
        """O usuario pediu explicitamente os graficos e a tabela do SPDM."""
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        for canvas_id in ("fabCurve", "fabCampChart", "fabStageChart"):
            self.assertIn(f'id="{canvas_id}"', html)
        self.assertIn("spanGaps: true", html)
        self.assertIn("CHARTS.curve.report_dates", html)
        self.assertIn("CHARTS.curve.point_types", html)
        self.assertIn("W10 reportado em", html)
        self.assertIn("Referência inicial (não reportada)", html)
        self.assertIn('id="fabChartsData"', html)
        self.assertIn('id="fabStagesMeta"', html)
        # subnivel busca no banco do DATAFY via endpoint, nada embutido no HTML
        self.assertIn("data-fab-detail-url", html)
        self.assertNotIn('id="fabDetailData"', html)
        self.assertIn('class="fab-table"', html)
        self.assertIn('id="fabBody"', html)
        # uma coluna por estagio do P6, com o rotulo curto
        for short_label in ("PreFab", "Fit-up", "Weld", "NDT", "PWHT", "Hydro", "Paint"):
            self.assertIn(short_label, html)

    @patch("apps.core.skyline_source.timezone.localdate", return_value=date(2026, 9, 3))
    def test_delivery_grid_sits_below_fabrication_with_rundown_and_skyline(self, _localdate):
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        self.assertTrue(response.context["rundown"]["available"])
        self.assertTrue(response.context["skyline"]["available"])
        skyline_dates = {
            item["date"]
            for item in response.context["skyline"]["charts"]["dates"]
        }
        self.assertEqual(len(skyline_dates), 18)
        self.assertNotIn("2026-09-02", skyline_dates)
        self.assertNotIn("2026-09-03", skyline_dates)
        self.assertIn("2026-09-04", skyline_dates)
        self.assertIn("2026-12-18", skyline_dates)
        self.assertIn('class="fab-delivery-grid"', html)
        self.assertIn('id="fabRundownData"', html)
        self.assertIn('id="fabRundownChart"', html)
        self.assertIn('id="fabSkylineData"', html)
        self.assertIn('id="fabSkylinePlot"', html)
        self.assertIn('id="fabSkylineModal"', html)
        self.assertIn("Piping ISO rundown", html)
        self.assertIn('data-snapshot-date="2026-09-02"', html)
        self.assertIn('aria-label="Rundown summary"', html)
        self.assertIn("Scope", html)
        self.assertIn("607 <span>spools</span>", html)
        self.assertIn("Baseline zero", html)
        self.assertIn("26 Nov 26", html)
        self.assertIn("Lookahead zero", html)
        self.assertIn("15 Dec 26", html)
        self.assertIn("Zero-date gap", html)
        self.assertIn("+19 <span>days</span>", html)
        self.assertIn('class="fab-rundown-legend"', html)
        self.assertIn('class="fab-rundown-legend" role="group"', html)
        self.assertIn("Daily releases", html)
        self.assertIn("Data date · 02 Sep 26", html)
        self.assertIn("Source · Runddown!T1:X75 · reconciled schedule · snapshot 02 Sep 26", html)
        skyline = response.context["skyline"]
        self.assertEqual(skyline["kpis"]["scope_spools"], 607)
        self.assertEqual(skyline["kpis"]["performed_spools"], 48)
        self.assertEqual(skyline["kpis"]["remaining_spools"], 559)
        self.assertEqual(skyline["source"]["forecast_scope"], "Planilha1!A1:E176")
        self.assertEqual(skyline["source"]["as_of_date"], "2026-09-03")
        schedules = response.context["skyline_schedules"]
        self.assertEqual(set(schedules), {"ros", "aveon", "installation"})
        self.assertEqual(schedules["ros"]["kpis"], skyline["kpis"])
        self.assertEqual(schedules["ros"]["source"], skyline["source"])
        self.assertTrue(schedules["installation"]["source"]["is_sample"])
        self.assertEqual(schedules["installation"]["source"]["discipline"], "piping")

        modes = response.context["rundown_modes"]
        self.assertEqual(set(modes), {"fabrication", "installation"})
        self.assertEqual(set(modes["fabrication"]["disciplines"]), {"piping", "electrical", "structural"})
        piping = modes["fabrication"]["disciplines"]["piping"]
        self.assertEqual(piping["kpis"], response.context["rundown"]["kpis"])
        self.assertEqual(piping["charts"], response.context["rundown"]["charts"])
        self.assertFalse(piping["source"]["is_sample"])
        self.assertTrue(modes["installation"]["disciplines"]["piping"]["source"]["is_sample"])

        for element_id in (
            "fabRundownModes", "fabRundownDiscipline", "fabRundownSample",
            "fabRundownEmpty", "fabSkylineSchedules", "fabSkylineTitle",
            "fabSkylineSample", "fabSkylineCutoffDate", "fabSkylineViewToggle",
            "fabSkylineForecastBand", "fabSkylineActualBand", "fabSkylineBoxDetail",
        ):
            self.assertTrue(f'id="{element_id}"' in html, f"Missing delivery control: {element_id}")
        buttons = re.findall(
            r'<button\b([^>]*\bdata-skyline-schedule="[^"]+"[^>]*)>(.*?)</button>',
            html, re.DOTALL,
        )
        self.assertEqual(len(buttons), 3)
        for (attributes, label), key, title in zip(
            buttons, ("aveon", "ros", "installation"), ("Fabrication", "Wooden Box", "Installation")
        ):
            self.assertIn('data-skyline-schedule="' + key + '"', attributes)
            self.assertIn('aria-pressed="' + ("true" if key == "ros" else "false") + '"', attributes)
            self.assertEqual(label.strip(), title)
            self.assertLess(html.index('data-skyline-schedule="' + key + '"'), html.index('id="fabSkylineTitle"'))
        for text in (
            "Wooden Box skyline", "ROS baseline forecast and 60-day lookahead dates",
            "48 performed · 559 remaining", "On plan", "Delayed", "In progress / Partial",
            "shared by both scenarios", "Long line codes are shortened with an ellipsis",
            "Temporary completion proxy",
        ):
            self.assertTrue(text in html, f"Missing delivery summary: {text}")
        self.assertNotIn("Runddown!F5:G180", html)
        self.assertLess(html.index('class="fab-skyline-plot"'), html.index('class="fab-skyline-legend"'))
        self.assertLess(html.index('class="fab-skyline-legend"'), html.index('id="fabSkylinePlot"'))
        self.assertLess(html.index('id="fabBody"'), html.index('id="fabRundownChart"'))
        self.assertLess(html.index('id="fabRundownDiscipline"'), html.index('id="fabRundownChart"'))
        self.assertLess(html.index('id="fabRundownChart"'), html.index('id="fabSkylinePlot"'))
        self.assertLess(html.index('id="fabSkylinePlot"'), html.index('id="s05"'))
        # Source switching, chart rendering, units and unavailable states are
        # exercised by the Node controller tests, not JavaScript string matches.

    def test_fabrication_detail_endpoint_returns_json(self):
        """O subnivel do desenho e servido pelo endpoint que le o banco DATAFY."""
        response = self.client.get(reverse("core:fabrication_detail", args=[1]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("available", payload)
        self.assertIn("linked", payload)
        self.assertIn("tables", payload)

    def test_fabrication_section_degrades_when_spdm_is_unreachable(self):
        """Sem o Postgres do SPDM a secao mostra aviso, nao quebra o cockpit."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        fabrication = response.context["fabrication"]
        self.assertIn("available", fabrication)
        self.assertIn("kpis", fabrication)
        self.assertIn("charts", fabrication)

    @override_settings(DASHFY_SHOW_TRACKING=False)
    def test_section_nav_omits_tracking_until_release(self):
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        for target in ("s00", "s01", "s02", "s03", "s05"):
            self.assertIn(f'data-target="{target}"', html)
        self.assertNotIn('data-target="s04"', html)

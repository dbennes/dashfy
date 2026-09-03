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

        self.assertIn("height: 390px", card)
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
    def test_skyline_uses_single_column_towers_without_internal_scroll(self):
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
        plot = rule(".cockpit-v3 #s03 .fab-skyline-plot")
        labels = rule(".cockpit-v3 #s03 .fab-skyline-band-labels")
        matrix = rule(".cockpit-v3 #s03 .fab-skyline-matrix")
        week = rule(".cockpit-v3 #s03 .fab-skyline-week")
        half = rule(".cockpit-v3 #s03 .fab-skyline-half")
        grid = rule(".cockpit-v3 #s03 .fab-skyline-half::before")
        actual_grid = rule(".cockpit-v3 #s03 .fab-skyline-half.is-actual::before")
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
        self.assertIn("grid-column: 1", labels)
        self.assertIn("grid-row: 2", labels)
        self.assertIn("grid-column: 2", viewport)
        self.assertIn("grid-row: 2", viewport)
        self.assertIn("width: 100%", matrix)
        self.assertIn("min-width: 0", matrix)
        self.assertIn("grid-template-columns: repeat(var(--fab-skyline-week-count)", matrix)
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
        self.assertIn("to bottom", actual_grid)
        self.assertIn("inset: 2px 3px 0", actual_grid)
        self.assertIn("border-right: 1px dashed", week)
        self.assertIn("position: relative", half)
        self.assertIn("isolation: isolate", half)
        self.assertIn("background: transparent", half)
        self.assertIn("z-index: 1", total)
        self.assertIn("z-index: 1", stack)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", stack)
        self.assertIn("grid-auto-flow: row", stack)
        self.assertIn("grid-auto-rows: 15px", stack)
        self.assertIn("height: 15px", item)
        self.assertIn("--fab-skyline-fill", item)
        self.assertNotIn(".fab-skyline-total-unit { display: none; }", css)


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
        self.assertIn("Source · Runddown!T1:X79 · snapshot 02 Sep 26", html)
        self.assertIn("Fabrication skyline", html)
        self.assertIn("Baseline forecast above", html)
        self.assertIn("Actual below from Runddown F:G dates before 03 Sep 26", html)
        self.assertIn("21 actual / 607 forecast spools", html)
        self.assertIn("<span>Forecast</span><span></span><span>Actual</span>", html)
        self.assertIn("Forecast · Planilha1 baseline", html)
        self.assertIn("Actual · F:G before cutoff", html)
        self.assertIn("Current week · cutoff", html)
        self.assertIn("Shade intensity · spool quantity", html)
        self.assertLess(html.index('class="fab-skyline-plot"'), html.index('class="fab-skyline-legend"'))
        self.assertLess(html.index('class="fab-skyline-legend"'), html.index('id="fabSkylinePlot"'))
        self.assertIn("Weekly forecast and actual skyline with all scheduled lines visible", html)
        self.assertNotIn("scroll horizontally to inspect all weeks", html)
        self.assertIn("Runddown!F5:G180", html)
        self.assertIn("Temporary Actual rule", html)
        for label in (
            "Lookahead releases",
            "Baseline releases",
            "Lookahead rundown",
            "Baseline rundown",
        ):
            self.assertIn(label, html)
        self.assertIn('id: "fabRundownDataDate"', html)
        self.assertIn('legend: { display: false }', html)
        self.assertIn('text: "REMAINING SPOOLS"', html)
        self.assertIn('text: "DAILY RELEASES · SPOOLS"', html)
        self.assertIn('return "Remaining gap: "', html)
        self.assertIn('offset: true', html)
        self.assertIn('stepSize: 100', html)
        self.assertIn('stepSize: 10', html)
        self.assertIn('(prefers-reduced-motion: reduce)', html)
        self.assertIn("function tickLimitFor(width)", html)
        self.assertIn("onResize: function (chart, size)", html)
        self.assertIn('metricKey: "lookaheadRemaining"', html)
        self.assertIn('metricKey: "baselineRemaining"', html)
        self.assertIn('showRundownError("Rundown chart could not be loaded.")', html)
        self.assertIn('showRundownError("Rundown chart could not be rendered.")', html)
        self.assertIn('id="fabRundownEmpty" role="status"', html)
        self.assertNotIn("REMAINING ISO LINES", html)
        self.assertNotIn("DAILY ISO LINES", html)
        self.assertLess(html.index('id="fabBody"'), html.index('id="fabRundownChart"'))
        self.assertLess(html.index('id="fabRundownChart"'), html.index('id="fabSkylinePlot"'))
        self.assertLess(html.index('id="fabRundownChart"'), html.index('id="s05"'))
        self.assertIn("fabSkylineInit", html)
        self.assertIn("function hasSkylineData(week)", html)
        self.assertIn("data.weeks.filter(hasSkylineData)", html)
        self.assertIn("Number(week.forecast_total || 0) > 0", html)
        self.assertNotIn('column.classList.add("has-gap-before")', html)
        self.assertNotIn("column.dataset.omittedWeeks", html)
        self.assertNotIn('gapMarker.className = "fab-skyline-gap-marker"', html)
        self.assertNotIn("function statusCell", html)
        self.assertIn("function orderedSegments(entries, scenarioKey)", html)
        self.assertIn("function stackRows(entryCount)", html)
        self.assertNotIn("function stackLayout(entryCount)", html)
        self.assertNotIn("maxDateColumns", html)
        self.assertNotIn("targetRowsPerColumn", html)
        self.assertNotIn("var maxStackRows", html)
        self.assertIn('quantity.textContent = Number(segment.spools || 0).toLocaleString("en-US")', html)
        self.assertNotIn("quantity.textContent = spoolLabel(segment.spools)", html)
        self.assertNotIn('totalNode.appendChild(document.createTextNode(" spools"))', html)
        self.assertIn('totalUnit.className = "fab-skyline-total-unit"', html)
        self.assertIn('totalUnit.textContent = total === 1 ? "spool" : "spools"', html)
        self.assertIn('totalNode.setAttribute("aria-label", "Weekly total: " + spoolLabel(total))', html)
        self.assertIn("function loadClass(value)", html)
        self.assertIn('return "is-load-high"', html)
        self.assertIn("var linePitch = 16", html)
        self.assertIn("var actualHeight = Math.max(76", html)
        self.assertIn('matrix.style.setProperty("--fab-skyline-week-count", String(weeks.length))', html)
        self.assertNotIn("weekLanes", html)
        self.assertNotIn("column.style.gridColumn", html)
        self.assertIn("--fab-skyline-forecast-height", html)
        self.assertNotIn("function visibleSegments", html)
        self.assertNotIn('line: "+" + hidden.length + " lines"', html)

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

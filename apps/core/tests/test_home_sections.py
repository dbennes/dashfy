from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


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

    def test_rundown_chart_sits_below_fabrication_and_keeps_all_excel_series(self):
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        self.assertTrue(response.context["rundown"]["available"])
        self.assertIn('id="fabRundownData"', html)
        self.assertIn('id="fabRundownChart"', html)
        self.assertIn("Piping ISO rundown", html)
        for label in (
            "Lookahead daily",
            "Baseline daily",
            "Lookahead rundown",
            "Baseline rundown",
        ):
            self.assertIn(label, html)
        self.assertLess(html.index('id="fabBody"'), html.index('id="fabRundownChart"'))
        self.assertLess(html.index('id="fabRundownChart"'), html.index('id="s05"'))

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

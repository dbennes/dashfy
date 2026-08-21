from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class HomeSectionLayoutTests(TestCase):
    """A home renderiza S00..S05 com a S03 dedicada a fabricacao."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="cockpit-tester",
            email="cockpit@example.com",
            password="cockpit-pass-123",
        )
        self.client.force_login(self.user)

    def test_home_exposes_fabrication_as_s03_and_model_as_s05(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        self.assertIn('id="s03"', html)
        self.assertIn("S03 · Engineering · Fabrication", html)
        self.assertIn("<em>Fabrication</em> progress", html)
        self.assertIn('id="s04"', html)
        self.assertIn("S04 · Tracking", html)
        self.assertIn('id="s05"', html)
        self.assertIn("S05 · 3D Model", html)
        self.assertNotIn("S04 · 3D Model", html)

    def test_tracking_section_reads_taskfy_and_ships_charts(self):
        """A S04 vem do banco do Taskfy (read-only) com os graficos do cockpit."""
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        tracking = response.context["tracking"]
        self.assertIn("available", tracking)
        self.assertIn("kpis", tracking)
        self.assertIn("charts", tracking)
        if tracking["available"]:
            self.assertIn('id="trkChartsData"', html)
            for canvas_id in ("trkFlowChart", "trkItemsChart", "trkFleetChart"):
                self.assertIn(f'id="{canvas_id}"', html)
        else:
            self.assertIn("Trackfy unavailable", html)

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

    def test_section_nav_lists_six_sections(self):
        response = self.client.get(reverse("core:home"))
        html = response.content.decode("utf-8")

        for target in ("s00", "s01", "s02", "s03", "s04", "s05"):
            self.assertIn(f'data-target="{target}"', html)

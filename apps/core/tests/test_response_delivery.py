import gzip
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.http import HttpResponse
from django.middleware.gzip import GZipMiddleware
from django.test import RequestFactory, SimpleTestCase

from apps.core.response_timing import ResponseTiming


class ResponseDeliveryTests(SimpleTestCase):
    def test_login_uses_real_middleware_stack_and_compresses_html(self):
        response = self.client.get("/accounts/login/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Encoding"], "gzip")
        html = gzip.decompress(response.content).decode()
        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertIn("Accept-Encoding", response["Vary"])
        self.assertIn("Cookie", response["Vary"])
        self.assertNotIn("cdn.plot.ly", html)
        self.assertNotIn("echarts.min.js", html)
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)

    def test_client_without_gzip_keeps_readable_login(self):
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Encoding", response)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_compression_preserves_unicode_and_timing_on_large_response(self):
        raw = ('<tr><td>Fabricação — Piping</td><td>24/09/2026</td></tr>' * 10000).encode()
        response = HttpResponse(raw)
        with patch("apps.core.response_timing.perf_counter", side_effect=[10, 10.5, 11]):
            timing = ResponseTiming()
            timing.mark("management")
            timing.attach(response)
        result = GZipMiddleware(lambda request: response)(RequestFactory().get("/", HTTP_ACCEPT_ENCODING="gzip"))
        self.assertEqual(gzip.decompress(result.content), raw)
        self.assertLess(len(result.content), len(raw) // 10)
        self.assertEqual(result["Server-Timing"], "management;dur=500.0, total;dur=1000.0")

    def test_plotly_remains_available_on_pages_that_use_it(self):
        templates = Path(settings.BASE_DIR) / "templates"
        for name in ("datafy/home.html", "datafy/indicators.html", "taskfy/home.html"):
            text = (templates / name).read_text(encoding="utf-8")
            self.assertIn("{% block vendor_js %}", text)
            self.assertIn("https://cdn.plot.ly/plotly-2.32.0.min.js", text)

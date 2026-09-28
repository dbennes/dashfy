from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.accounts.models import User
from apps.core import real_sources, views
from apps.core.dashboard_cache import fresh_sources, cached_dashboard_source, cache as source_cache


class PriorityDashboardTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.user = User(username="test", role=User.Role.ADMIN)
        self.request.session = {}
        cache.clear()
        self.addCleanup(cache.clear)

    def test_first_response_has_history_without_loading_operational_sources(self):
        with patch.object(real_sources, "management_dashboard", side_effect=AssertionError("heavy source")), \
             patch.object(views.fabrication_source, "fabrication_progress_safe", side_effect=AssertionError("heavy source")):
            response = views.home_shell_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sectionNotesDialog"')
        self.assertContains(response, 'data-note-panel="piping-rundown"')
        self.assertContains(response, 'data-note-panel="wooden-box-skyline"')
        self.assertContains(response, "Processing…")
        self.assertContains(response, 'class="dashboard-history"')
        self.assertContains(response, 'data-loading="true" aria-busy="true" inert')
        self.assertNotContains(response, "dashboard-placeholder")
        self.assertNotContains(response, "Loading current data")
        self.assertNotContains(response, 'id="fabRundownModes"')
        self.assertLess(len(response.content), 65000)
        self.assertIn("no-store", response["Cache-Control"])

    def test_live_source_read_bypasses_cached_values_and_is_request_local(self):
        source_cache.set("priority-test", "old", 300)
        loader = Mock(return_value={"value": 1})
        source = cached_dashboard_source("priority-test")(loader)
        self.assertEqual(source(), {"value": 1})
        loader.return_value = {"value": 2}
        with fresh_sources():
            self.assertIsNone(source_cache.get("priority-test"))
            self.assertEqual(source(), {"value": 2})
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(source_cache.get, "priority-test").result(), "old")
        self.assertEqual(source(), {"value": 1})

    def test_source_failure_never_uses_old_supply_snapshot_on_fresh_request(self):
        with fresh_sources(), patch.object(real_sources, "_construction_datafy", side_effect=OSError("offline")), \
             patch.object(real_sources.DatafySupplySnapshot.objects, "filter", side_effect=AssertionError("stale fallback")):
            result = real_sources._construction_datafy_snapshot({})
        self.assertFalse(result["available"])
        self.assertIn("no older snapshot", result["snapshot_error"])

    def test_fragment_endpoint_reads_fresh_and_is_not_browser_cached(self):
        source_cache.set("priority-test", "old", 300)
        def render(request):
            self.assertTrue(request.dashboard_fragment)
            self.assertIsNone(source_cache.get("priority-test"))
            return HttpResponse("current")
        with patch.object(views, "home_view", side_effect=render):
            response = views.dashboard_content_view(self.request)
        self.assertEqual(response["X-Dashboard-Content"], "1")
        self.assertIn("no-store", response["Cache-Control"])

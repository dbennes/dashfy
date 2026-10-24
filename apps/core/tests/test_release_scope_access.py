"""Role selection, request isolation and caches must agree on drawing scope."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache as django_cache
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core.dashboard_cache import cache, cached_dashboard_source
from apps.core.release_middleware import DrawingReleaseScopeMiddleware, SESSION_KEY
from apps.core.release_scope import (
    current_release_scope, document_scope_sql, release_scope_context,
)


class _ScopeSelector(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.in_selector = False
        self.present = False
        self.options = []
        self.current = None
        self.hidden = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "select" and attrs.get("id") == "drawing-release-scope":
            self.in_selector = self.present = True
        elif self.in_selector and tag == "option":
            self.current = {"value": attrs.get("value"), "label": "", "selected": "selected" in attrs}
        elif tag == "input" and attrs.get("type") == "hidden":
            self.hidden.append((attrs.get("name"), attrs.get("value")))

    def handle_data(self, data):
        if self.in_selector and self.current is not None:
            self.current["label"] += data

    def handle_endtag(self, tag):
        if tag == "option" and self.current is not None:
            self.current["label"] = self.current["label"].strip()
            self.options.append(self.current)
            self.current = None
        elif tag == "select":
            self.in_selector = False


class ReleaseScopeContextTests(SimpleTestCase):
    def tearDown(self):
        self.assertEqual(current_release_scope(), "official")

    def test_nested_scopes_restore_previous_scope_even_after_exception(self):
        with release_scope_context("all"):
            self.assertEqual(current_release_scope(), "all")
            with release_scope_context("preparing"):
                self.assertEqual(current_release_scope(), "preparing")
            self.assertEqual(current_release_scope(), "all")
            with self.assertRaisesRegex(RuntimeError, "source failed"):
                with release_scope_context("preparing"):
                    raise RuntimeError("source failed")
            self.assertEqual(current_release_scope(), "all")

    def test_invalid_scope_never_changes_current_context(self):
        with release_scope_context("preparing"):
            with self.assertRaises(ValueError):
                with release_scope_context("unknown"):
                    self.fail("Invalid scope entered")
            self.assertEqual(current_release_scope(), "preparing")

    def test_parallel_requests_cannot_observe_each_others_context(self):
        rendezvous = Barrier(3)

        def worker(scope):
            previous = current_release_scope()
            with release_scope_context(scope):
                rendezvous.wait(timeout=5)
                observed = current_release_scope()
                sql = document_scope_sql("drawing")
            return observed, sql, previous, current_release_scope()

        with release_scope_context("all"), ThreadPoolExecutor(max_workers=2) as executor:
            preparing = executor.submit(worker, "preparing")
            official = executor.submit(worker, "official")
            rendezvous.wait(timeout=5)
            self.assertEqual(current_release_scope(), "all")
            for expected, result in (("preparing", preparing.result(timeout=5)), ("official", official.result(timeout=5))):
                self.assertEqual(result[0], expected)
                self.assertEqual(result[1], f"drawing.release_status = '{expected}'")
                self.assertEqual(result[2], result[3])

    def test_sql_predicate_is_explicit_for_each_scope_and_rejects_unsafe_aliases(self):
        for scope in ("official", "preparing", "all"):
            with self.subTest(scope=scope), release_scope_context(scope):
                expected = "d.release_status in ('official', 'preparing')" if scope == "all" else f"d.release_status = '{scope}'"
                self.assertEqual(document_scope_sql("d"), expected)
        self.assertEqual(document_scope_sql(""), "release_status = 'official'")
        for alias in ("d; DROP TABLE core_document", "d.release_status", "d --", "1invalid"):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                document_scope_sql(alias)


@override_settings(DASHFY_SOURCE_CACHE_SECONDS=60)
class ReleaseScopeCacheTests(SimpleTestCase):
    def setUp(self):
        django_cache.clear()

    def tearDown(self):
        django_cache.clear()
        self.assertEqual(current_release_scope(), "official")

    def test_manual_source_cache_never_reuses_another_scopes_payload(self):
        for scope in ("preparing", "all", "official"):
            with self.subTest(scope=scope), release_scope_context(scope):
                self.assertIsNone(cache.get("same-dashboard-payload"))
                cache.set("same-dashboard-payload", {"scope": scope}, timeout=60)
        for scope in ("official", "preparing", "all"):
            with release_scope_context(scope):
                self.assertEqual(cache.get("same-dashboard-payload"), {"scope": scope})

    def test_decorated_source_has_independent_cached_results_for_identical_arguments(self):
        loads = []

        @cached_dashboard_source("release-scope-access-test")
        def source(campaign):
            scope = current_release_scope()
            loads.append((campaign, scope))
            return {"scope": scope, "campaign": campaign}

        for scope in ("preparing", "official", "all", "official", "all", "preparing"):
            with release_scope_context(scope):
                self.assertEqual(source("BN-EPC1"), {"scope": scope, "campaign": "BN-EPC1"})
        self.assertEqual(loads, [("BN-EPC1", "preparing"), ("BN-EPC1", "official"), ("BN-EPC1", "all")])


class ReleaseScopeMiddlewareTests(SimpleTestCase):
    def request(self, user, scope):
        request = RequestFactory().get("/model-review/", {"release_scope": scope})
        request.user = user
        request.session = {}
        return request

    def test_middleware_resets_context_when_downstream_raises(self):
        def failing_view(request):
            self.assertEqual(current_release_scope(), "preparing")
            raise RuntimeError("source failure")

        request = self.request(User(role=User.Role.PLANNING), "preparing")
        with release_scope_context("all"):
            with self.assertRaisesRegex(RuntimeError, "source failure"):
                DrawingReleaseScopeMiddleware(failing_view)(request)
            self.assertEqual(current_release_scope(), "all")
        self.assertEqual(current_release_scope(), "official")

    def test_anonymous_forged_scope_is_normalized_before_a_source_runs(self):
        request = self.request(AnonymousUser(), "preparing")
        response = DrawingReleaseScopeMiddleware(
            lambda req: JsonResponse({"scope": current_release_scope()}),
        )(request)
        self.assertJSONEqual(response.content, {"scope": "official"})
        self.assertEqual(request.release_scope, "official")
        self.assertEqual(request.session, {})
        self.assertEqual(current_release_scope(), "official")


class ReleaseScopeClientAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: User.objects.create_user(username=f"release-{role}", role=role)
            for role in (User.Role.ADMIN, User.Role.PLANNING, User.Role.SUPPLY, User.Role.VIEWER, User.Role.ANALYST, User.Role.CLIENT)
        }

    def setUp(self):
        # The home shell and mocked API need no external DATAFY/Taskfy reads.
        network = patch("psycopg2.connect", side_effect=AssertionError("Live database access is forbidden"))
        network.start()
        self.addCleanup(network.stop)
        review = patch("apps.core.model_review.review_payload", side_effect=lambda: {"scope": current_release_scope()})
        self.review = review.start()
        self.addCleanup(review.stop)

    def tearDown(self):
        self.assertEqual(current_release_scope(), "official")

    def test_admin_planning_and_supply_topbar_offer_official_preparing_and_both(self):
        for role in (User.Role.ADMIN, User.Role.PLANNING, User.Role.SUPPLY):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                response = self.client.get(reverse("core:home"))
                self.assertEqual(response.status_code, 200)
                selector = _ScopeSelector(response)
                self.assertTrue(selector.present)
                self.assertEqual([(option["value"], option["label"]) for option in selector.options], [
                    ("official", "Official"), ("preparing", "Preparing"), ("all", "Both"),
                ])
                self.assertEqual([option["value"] for option in selector.options if option["selected"]], ["official"])
                self.assertTrue(response.context["can_view_preparing"])
                self.assertEqual(response.context["drawing_release_scope"], "official")

    def test_authorized_get_selection_persists_across_home_and_model_review_requests(self):
        for role in (User.Role.ADMIN, User.Role.PLANNING, User.Role.SUPPLY):
            for scope in ("preparing", "all", "official"):
                with self.subTest(role=role, scope=scope):
                    self.client.force_login(self.users[role])
                    response = self.client.get(reverse("core:home"), {"release_scope": scope, "campaign": "BN-EPC1"})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["drawing_release_scope"], scope)
                    selector = _ScopeSelector(response)
                    self.assertEqual([option["value"] for option in selector.options if option["selected"]], [scope])
                    self.assertIn(("campaign", "BN-EPC1"), selector.hidden)
                    self.assertEqual(self.client.session[SESSION_KEY], scope)
                    api = self.client.get(reverse("core:model_review"))
                    self.assertEqual(api.status_code, 200)
                    self.assertEqual(api.json(), {"scope": scope})
                    self.assertEqual(api["X-Drawing-Release-Scope"], scope)
                    self.assertEqual(current_release_scope(), "official")

    def test_viewer_forged_query_and_preparing_session_are_demoted_before_api_or_html(self):
        self.client.force_login(self.users[User.Role.VIEWER])
        session = self.client.session
        session[SESSION_KEY] = "preparing"
        session.save()
        response = self.client.get(reverse("core:home"), {"release_scope": "all"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(_ScopeSelector(response).present)
        self.assertEqual(response.context["drawing_release_scope"], "official")
        self.assertFalse(response.context["can_view_preparing"])
        self.assertEqual(self.client.session[SESSION_KEY], "official")
        api = self.client.get(reverse("core:model_review"), {"release_scope": "preparing"})
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json(), {"scope": "official"})

    def test_role_demotion_clears_preparing_selection_without_relogin(self):
        planner = self.users[User.Role.PLANNING]
        self.client.force_login(planner)
        selected = self.client.get(reverse("core:model_review"), {"release_scope": "preparing"})
        self.assertEqual(selected.json(), {"scope": "preparing"})
        User.objects.filter(pk=planner.pk).update(role=User.Role.VIEWER)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["drawing_release_scope"], "official")
        self.assertFalse(_ScopeSelector(response).present)
        self.assertEqual(self.client.session[SESSION_KEY], "official")
        self.assertEqual(self.client.get(reverse("core:model_review")).json(), {"scope": "official"})

    def test_legacy_analyst_and_client_profiles_keep_official_only_access(self):
        for role in (User.Role.ANALYST, User.Role.CLIENT):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                session = self.client.session
                session[SESSION_KEY] = "all"
                session.save()
                response = self.client.get(reverse("core:home"), {"release_scope": "preparing"})
                self.assertEqual(response.status_code, 200)
                self.assertFalse(_ScopeSelector(response).present)
                self.assertEqual(self.client.session[SESSION_KEY], "official")
                self.assertEqual(self.client.get(reverse("core:model_review")).json(), {"scope": "official"})

    def test_invalid_scope_is_normalized_for_authorized_profile(self):
        self.client.force_login(self.users[User.Role.PLANNING])
        response = self.client.get(reverse("core:model_review"), {"release_scope": "forged"})
        self.assertEqual(response.json(), {"scope": "official"})
        self.assertEqual(self.client.session[SESSION_KEY], "official")

    def test_authenticated_html_and_api_responses_are_private_and_vary_by_cookie(self):
        self.client.force_login(self.users[User.Role.PLANNING])
        for url in (reverse("core:home"), reverse("core:model_review")):
            with self.subTest(url=url):
                response = self.client.get(url, {"release_scope": "preparing"})
                self.assertEqual(response.status_code, 200)
                directives = {directive.strip().lower() for directive in response["Cache-Control"].split(",")}
                self.assertIn("private", directives)
                self.assertIn("no-store", directives)
                self.assertIn("cookie", {header.strip().lower() for header in response["Vary"].split(",")})
                self.assertEqual(response["X-Drawing-Release-Scope"], "preparing")

    def test_anonymous_home_and_api_never_call_dashboard_sources(self):
        response = self.client.get(reverse("core:home"), {"release_scope": "preparing"})
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse("core:model_review"), {"release_scope": "all"})
        self.assertEqual(response.status_code, 401)
        self.review.assert_not_called()
        self.assertEqual(current_release_scope(), "official")

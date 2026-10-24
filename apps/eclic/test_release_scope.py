from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from django.http import HttpResponse

from apps.accounts.models import Client, ModulePermission, User
from apps.core.real_sources import EngineeringScopeUnavailable
from apps.eclic.models import Document
from config.urls import urlpatterns as application_urls


urlpatterns = [route for route in application_urls
               if getattr(route, "name", None) != "legacy_modules_disabled"
               and getattr(route, "namespace", None) not in {"datafy", "taskfy", "schedule", "eclic"}]
urlpatterns += [path("eclic/", include("apps.eclic.urls", namespace="eclic"))]
# Base navigation reverses these unrelated legacy home links. They do not
# participate in this test and must not import their plotting/source stacks.
urlpatterns += [path(f"{name}/", include(([path("", lambda request: HttpResponse(), name="home")], name), namespace=name))
                for name in ("datafy", "taskfy", "schedule")]


@override_settings(ROOT_URLCONF=__name__, DASHFY_ENABLE_LEGACY_MODULES=True)
class LegacyEClicReleaseScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client_a = Client.objects.create(name="Scope client A", slug="scope-a")
        cls.client_b = Client.objects.create(name="Scope client B", slug="scope-b")
        cls.viewer = User.objects.create_user(username="legacy-viewer", role="viewer", client=cls.client_a)
        cls.planner = User.objects.create_user(username="legacy-planner", role="planning", client=cls.client_a)
        cls.denied = User.objects.create_user(username="legacy-denied", role="viewer", client=cls.client_a)
        for user in (cls.viewer, cls.planner):
            ModulePermission.objects.create(user=user, module="eclic", can_view=True)
        cls.official, cls.preparing, cls.legacy = [Document.objects.create(
            client=cls.client_a, external_id=code, code=code, title=f"Private {code}",
        ) for code in ("SCOPE-OFFICIAL", "SCOPE-PREPARING", "SCOPE-LEGACY")]
        cls.other_client = Document.objects.create(client=cls.client_b, external_id="SCOPE-OTHER",
                                                   code="SCOPE-OTHER", title="Other client drawing")

    def setUp(self):
        classification = patch("apps.core.real_sources._engineering_release_index", return_value={
            self.official.code: {"official"}, self.preparing.code: {"preparing"},
            self.other_client.code: {"preparing"},
        })
        self.classification = classification.start()
        self.addCleanup(classification.stop)
        network = patch("psycopg2.connect", side_effect=AssertionError("Live source access forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.client.force_login(self.viewer)

    def test_viewer_forged_preparing_list_export_and_direct_pk_remain_official_only(self):
        params = {"release_scope": "preparing"}
        home = self.client.get(reverse("eclic:home"), params)
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home.context["kpis"]["total"], 2)
        listing = self.client.get(reverse("eclic:document_list"), params)
        self.assertEqual({row.pk for row in listing.context["page_obj"]}, {self.official.pk, self.legacy.pk})
        exported = self.client.get(reverse("eclic:document_list"), {**params, "format": "json"})
        self.assertEqual(exported.status_code, 200)
        self.assertContains(exported, self.official.code)
        self.assertNotContains(exported, self.preparing.code)
        self.assertNotContains(exported, self.other_client.code)
        hidden = self.client.get(reverse("eclic:document_detail", args=[self.preparing.pk]), params)
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(self.client.get(reverse("eclic:document_detail", args=[self.official.pk])).status_code, 200)

    def test_planning_scope_selection_keeps_client_filter_in_every_view(self):
        self.client.force_login(self.planner)
        for scope, expected in (("official", {self.official.pk, self.legacy.pk}),
                                ("preparing", {self.preparing.pk}),
                                ("all", {self.official.pk, self.preparing.pk, self.legacy.pk})):
            with self.subTest(scope=scope):
                response = self.client.get(reverse("eclic:document_list"), {"release_scope": scope})
                self.assertEqual(response.status_code, 200)
                self.assertEqual({row.pk for row in response.context["page_obj"]}, expected)
                exported = self.client.get(reverse("eclic:document_list"), {"release_scope": scope, "format": "csv"})
                self.assertEqual(exported.status_code, 200)
                self.assertNotContains(exported, self.other_client.code)
        self.assertEqual(self.client.get(reverse("eclic:document_detail", args=[self.other_client.pk]),
                                         {"release_scope": "all"}).status_code, 404)

    def test_unavailable_classification_returns_503_instead_of_unfiltered_records(self):
        self.classification.side_effect = EngineeringScopeUnavailable("Fixture classification offline")
        for url, params in ((reverse("eclic:home"), {}),
                            (reverse("eclic:document_list"), {}),
                            (reverse("eclic:document_list"), {"format": "json"}),
                            (reverse("eclic:document_detail", args=[self.official.pk]), {})):
            with self.subTest(url=url, params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(self.official.code, response.content.decode())
                self.assertNotIn(self.preparing.code, response.content.decode())

    def test_module_permission_is_checked_before_classification(self):
        self.client.force_login(self.denied)
        response = self.client.get(reverse("eclic:document_list"), {"release_scope": "preparing"})
        self.assertEqual(response.status_code, 403)
        self.classification.assert_not_called()

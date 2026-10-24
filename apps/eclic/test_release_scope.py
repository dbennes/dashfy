from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from django.http import HttpResponse

from apps.accounts.models import Client, ModulePermission, User
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
        network = patch("psycopg2.connect", side_effect=AssertionError("Live source access forbidden"))
        self.network = network.start()
        self.addCleanup(network.stop)
        self.client.force_login(self.viewer)

    def test_external_eclic_documents_remain_visible_independent_of_datafy_selection(self):
        params = {"release_scope": "preparing"}
        home = self.client.get(reverse("eclic:home"), params)
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home.context["kpis"]["total"], 3)
        listing = self.client.get(reverse("eclic:document_list"), params)
        self.assertEqual({row.pk for row in listing.context["page_obj"]}, {self.official.pk, self.preparing.pk, self.legacy.pk})
        exported = self.client.get(reverse("eclic:document_list"), {**params, "format": "json"})
        self.assertEqual(exported.status_code, 200)
        self.assertContains(exported, self.official.code)
        self.assertContains(exported, self.preparing.code)
        self.assertNotContains(exported, self.other_client.code)
        detail = self.client.get(reverse("eclic:document_detail", args=[self.preparing.pk]), params)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(self.client.get(reverse("eclic:document_detail", args=[self.official.pk])).status_code, 200)
        self.network.assert_not_called()

    def test_planning_scope_selection_keeps_client_filter_in_every_view(self):
        self.client.force_login(self.planner)
        expected = {self.official.pk, self.preparing.pk, self.legacy.pk}
        for scope in ("official", "preparing", "all"):
            with self.subTest(scope=scope):
                response = self.client.get(reverse("eclic:document_list"), {"release_scope": scope})
                self.assertEqual(response.status_code, 200)
                self.assertEqual({row.pk for row in response.context["page_obj"]}, expected)
                exported = self.client.get(reverse("eclic:document_list"), {"release_scope": scope, "format": "csv"})
                self.assertEqual(exported.status_code, 200)
                for document in (self.official, self.preparing, self.legacy):
                    self.assertContains(exported, document.code)
                self.assertNotContains(exported, self.other_client.code)
        self.assertEqual(self.client.get(reverse("eclic:document_detail", args=[self.other_client.pk]),
                                         {"release_scope": "all"}).status_code, 404)

    def test_external_source_views_do_not_depend_on_datafy_availability(self):
        for url, params in ((reverse("eclic:home"), {}),
                            (reverse("eclic:document_list"), {}),
                            (reverse("eclic:document_list"), {"format": "json"}),
                            (reverse("eclic:document_detail", args=[self.official.pk]), {})):
            with self.subTest(url=url, params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
        self.network.assert_not_called()

        filtered = self.client.get(reverse("eclic:document_list"), {"code": self.preparing.code})
        self.assertEqual([document.pk for document in filtered.context["page_obj"]], [self.preparing.pk])

    def test_module_permission_is_still_required(self):
        self.client.force_login(self.denied)
        response = self.client.get(reverse("eclic:document_list"), {"release_scope": "preparing"})
        self.assertEqual(response.status_code, 403)
        self.network.assert_not_called()

"""Manual ROS updates are reviewed before changing either cockpit chart."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from io import BytesIO
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.core import ros_workbook, rundown_source, skyline_source
from apps.core.models import RosScheduleImport


@override_settings(
    DASHFY_SHOW_TRACKING=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class RosWorkbookViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="ros-admin", role=User.Role.ADMIN)
        cls.other_admin = User.objects.create_user(username="ros-other", role=User.Role.ADMIN)
        cls.viewer = User.objects.create_user(username="ros-viewer", role=User.Role.VIEWER)

    def setUp(self):
        self.client.force_login(self.admin)
        self.export_url = reverse("core:export_ros")
        self.import_url = reverse("core:import_ros")
        self.home_url = reverse("core:home")
        # These requests must never read or write the operational integration.
        self.enterContext(patch(
            "apps.core.real_sources._datafy_conn",
            side_effect=AssertionError("ROS view tests must not connect to operational DATAFY"),
        ))

    def exported_workbook(self):
        response = self.client.get(self.export_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn('filename="DASHFY_ROS.xlsx"', response["Content-Disposition"])
        return response.content

    def edited_workbook(self, *, delta=1, content=None):
        workbook = load_workbook(BytesIO(content or self.exported_workbook()))
        try:
            cell = workbook["ROS Schedule"]["E2"]
            before = cell.value
            cell.value += delta
            output = BytesIO()
            workbook.save(output)
            return output.getvalue(), before
        finally:
            workbook.close()

    def preview(self, content, *, filename="updated-ROS.xlsx"):
        return self.client.post(self.import_url, {
            "action": "preview",
            "ros_file": SimpleUploadedFile(filename, content, content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )),
        })

    def changed_preview(self, *, delta=1, content=None):
        changed, before = self.edited_workbook(delta=delta, content=content)
        response = self.preview(changed)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["preview_token"])
        return response, before

    def apply_preview(self, response):
        return self.client.post(self.import_url, {
            "action": "apply", "preview_token": response.context["preview_token"],
        })

    @contextmanager
    def isolated_home_sources(self):
        """Keep the real ROS display readers and replace independent systems."""
        current = ros_workbook.load_current_schedule()
        live_materials = {
            row[0]: {
                "supports": {"status": "ready", "source": "DATAFY supports"},
                "erection": {"status": "pending", "source": "DATAFY receipts"},
                "valves": {"status": "unknown", "source": "DATAFY"},
            }
            for row in current["skyline"]["rows"]
        }
        structural = rundown_source._empty_payload("Independent structural test source")
        structural["source"] = {"unit": "packages", "source_label": "AVEON schedule"}
        with (
            patch("apps.core.views.real_sources.management_dashboard", return_value={}),
            patch("apps.core.views.fabrication_source.fabrication_progress_safe", return_value={
                "available": False, "charts": {}, "stages": [],
            }) as progress,
            patch("apps.core.skyline_source.timezone.localdate", return_value=date(2026, 9, 14)),
            patch("apps.core.skyline_material_source.skyline_material_readiness", return_value=live_materials) as materials,
            patch("apps.core.skyline_aveon_source.aveon_skyline_safe", return_value=skyline_source._empty_payload()) as aveon,
            patch("apps.core.rundown_discipline_source.rundown_disciplines_safe", side_effect=lambda piping: {
                "piping": piping, "structural": structural,
            }) as disciplines,
        ):
            yield {"materials": materials, "aveon": aveon, "disciplines": disciplines,
                   "progress": progress, "live_materials": live_materials, "structural": structural}

    def test_exported_current_workbook_previews_without_creating_a_version(self):
        before = ros_workbook.load_current_schedule()
        response = self.preview(self.exported_workbook())

        self.assertContains(response, "The workbook matches the current ROS schedule.")
        self.assertTrue(response.context["unchanged"])
        self.assertNotIn("preview_token", response.context)
        self.assertFalse(RosScheduleImport.objects.exists())
        self.assertEqual(ros_workbook.load_current_schedule(), before)

    def test_changed_cell_preview_shows_old_and_new_values_without_writing(self):
        response, before = self.changed_preview()

        self.assertContains(response, "Review changes")
        self.assertContains(response, "Apply changes")
        self.assertEqual(response.context["preview"]["changes"], [{
            "row_id": "ROS-00001", "line": '1"-CC-423041', "field": "Spools",
            "before": before, "after": before + 1,
        }])
        self.assertEqual(response.context["scope_spools"], 607)
        self.assertEqual(response.context["preview_scope"], 608)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_apply_updates_both_home_charts_and_preserves_live_integration_inputs(self):
        initial = ros_workbook.load_current_schedule()
        preview, before = self.changed_preview()
        response = self.apply_preview(preview)

        self.assertRedirects(response, self.home_url + "#s03", fetch_redirect_response=False)
        batch = RosScheduleImport.objects.get()
        self.assertEqual(batch.imported_by, self.admin)
        self.assertEqual(batch.original_filename, "updated-ROS.xlsx")
        self.assertEqual(batch.base_revision, initial["revision"])
        self.assertEqual(batch.metadata["scope_spools"], 608)
        self.assertEqual(batch.payload["skyline"]["rows"][0][3], before + 1)
        self.assertEqual(batch.payload["skyline"]["rows"][0][:3], initial["skyline"]["rows"][0][:3])

        with self.isolated_home_sources() as live:
            home = self.client.get(self.home_url)

        self.assertEqual(home.status_code, 200)
        self.assertEqual(home.context["ros_schedule"]["batch"].pk, batch.pk)
        self.assertEqual(home.context["skyline"]["kpis"]["scope_spools"], 608)
        self.assertEqual(home.context["rundown"]["kpis"]["scope_total"], 608)
        self.assertEqual(home.context["rundown"]["charts"]["dates"], batch.payload["rundown"]["dates"])
        self.assertEqual(home.context["skyline"]["source"]["workbook"], "updated-ROS.xlsx")
        self.assertEqual(home.context["skyline"]["charts"]["material_readiness"], live["live_materials"])
        live["materials"].assert_called_once_with(
            sorted({row[0] for row in initial["skyline"]["rows"]}), as_of_date=date(2026, 9, 14),
        )
        live["progress"].assert_called_once_with()
        live["aveon"].assert_called_once()
        self.assertEqual(live["aveon"].call_args.args[0]["kpis"]["scope_spools"], 608)
        self.assertEqual(live["disciplines"].call_args.args[0]["kpis"]["scope_total"], 608)
        rendered_source = home.context["rundown_disciplines"]["structural"]["source"]
        self.assertEqual({key: rendered_source[key] for key in live["structural"]["source"]},
                         live["structural"]["source"])
        self.assertEqual(rendered_source["mode"], "fabrication")
        self.assertContains(home, self.import_url)
        self.assertContains(home, self.export_url)

    def test_export_after_apply_roundtrips_the_accepted_version_without_another_import(self):
        preview, _ = self.changed_preview()
        self.apply_preview(preview)
        accepted = RosScheduleImport.objects.get()
        before = deepcopy(accepted.payload)

        response = self.preview(self.exported_workbook())

        self.assertContains(response, "No changes were needed.")
        self.assertEqual(RosScheduleImport.objects.count(), 1)
        accepted.refresh_from_db()
        self.assertEqual(accepted.payload, before)
        page = self.client.get(self.import_url)
        self.assertContains(page, "updated-ROS.xlsx")
        self.assertContains(page, self.admin.username)

    def test_tampered_preview_token_cannot_apply(self):
        preview, _ = self.changed_preview()
        response = self.client.post(self.import_url, {
            "action": "apply", "preview_token": preview.context["preview_token"] + "x",
        })

        self.assertContains(response, "expired or is invalid", status_code=400)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_expired_preview_token_cannot_apply(self):
        preview, _ = self.changed_preview()
        future = time.time() + 1801
        with patch("django.core.signing.time.time", return_value=future):
            response = self.apply_preview(preview)

        self.assertContains(response, "expired or is invalid", status_code=400)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_another_administrator_cannot_apply_someone_elses_preview(self):
        preview, _ = self.changed_preview()
        self.client.force_login(self.other_admin)
        response = self.apply_preview(preview)

        self.assertContains(response, "using your own account", status_code=400)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_viewer_can_export_but_cannot_open_preview_or_apply_an_import(self):
        preview, _ = self.changed_preview()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.export_url).status_code, 200)
        self.assertEqual(self.client.get(self.import_url).status_code, 403)
        self.assertEqual(self.client.post(self.import_url, {"action": "preview"}).status_code, 403)
        self.assertEqual(self.apply_preview(preview).status_code, 403)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_anonymous_requests_redirect_to_login_without_exporting_or_importing(self):
        self.client.logout()
        for method, url in (("get", self.export_url), ("get", self.import_url), ("post", self.import_url)):
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("accounts:login")))
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_import_post_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(self.import_url, {"action": "preview"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_wrong_file_and_missing_upload_return_explanations_without_changes(self):
        for content, filename, expected in (
            (b"line,spools\nA,1", "schedule.csv", "Choose the exported ROS workbook"),
            (b"not an Excel archive", "schedule.xlsx", "valid .xlsx ROS workbook"),
        ):
            with self.subTest(filename=filename):
                self.assertContains(self.preview(content, filename=filename), expected, status_code=400)
        self.assertContains(self.client.post(self.import_url), "Choose the exported ROS workbook", status_code=400)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_upload_limit_is_reported_without_parsing(self):
        with patch("apps.core.ros_views.MAX_UPLOAD_BYTES", 5), patch("apps.core.ros_workbook.parse_ros_workbook") as parser:
            response = self.preview(b"too large")

        self.assertContains(response, "10 MB upload limit", status_code=400)
        parser.assert_not_called()
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_old_workbook_cannot_be_previewed_after_another_accepted_import(self):
        old_export = self.exported_workbook()
        preview, _ = self.changed_preview(content=old_export)
        self.apply_preview(preview)
        accepted = deepcopy(RosScheduleImport.objects.get().payload)

        response = self.preview(old_export)

        self.assertContains(response, "out of date", status_code=400)
        self.assertEqual(RosScheduleImport.objects.count(), 1)
        self.assertEqual(RosScheduleImport.objects.get().payload, accepted)

    def test_stale_preview_cannot_overwrite_an_import_accepted_after_preview(self):
        old_export = self.exported_workbook()
        earlier, _ = self.changed_preview(delta=1, content=old_export)
        newer, _ = self.changed_preview(delta=2, content=old_export)
        self.apply_preview(newer)
        accepted = deepcopy(RosScheduleImport.objects.get().payload)

        response = self.apply_preview(earlier)

        self.assertContains(response, "changed after this workbook was exported", status_code=400)
        self.assertEqual(RosScheduleImport.objects.count(), 1)
        self.assertEqual(RosScheduleImport.objects.get().payload, accepted)
        self.assertEqual(RosScheduleImport.objects.get().metadata["scope_spools"], 609)

    def test_replaying_an_applied_preview_does_not_create_another_version(self):
        preview, _ = self.changed_preview()
        self.apply_preview(preview)
        response = self.apply_preview(preview)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(RosScheduleImport.objects.count(), 1)

    def test_database_failure_returns_service_error_without_changing_the_schedule(self):
        preview, _ = self.changed_preview()
        with patch("apps.core.ros_workbook.apply_ros_import", side_effect=DatabaseError("test database unavailable")), patch("apps.core.ros_views.logger.exception"):
            response = self.apply_preview(preview)

        self.assertContains(response, "No changes were applied", status_code=503)
        self.assertFalse(RosScheduleImport.objects.exists())

    def test_database_read_failure_does_not_fall_back_to_the_original_home_snapshots(self):
        preview, _ = self.changed_preview()
        self.apply_preview(preview)
        with self.isolated_home_sources() as live:
            with (
                patch("apps.core.ros_workbook.load_current_schedule", side_effect=DatabaseError("test database unavailable")),
                patch("apps.core.skyline_source.fabrication_skyline_safe") as skyline,
                patch("apps.core.rundown_source.fabrication_rundown_safe") as rundown,
                patch("logging.Logger.exception"),
            ):
                response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["ros_schedule"])
        self.assertFalse(response.context["skyline"]["available"])
        self.assertFalse(response.context["rundown"]["available"])
        skyline.assert_not_called()
        rundown.assert_not_called()
        live["materials"].assert_not_called()
        self.assertEqual(RosScheduleImport.objects.count(), 1)

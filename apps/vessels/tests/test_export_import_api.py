from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.vessels import csvio
from apps.vessels.imports import import_report
from apps.vessels.models import Vessel, VesselPosition


@override_settings(
    AISSTREAM_API_KEY="test-backend-key-never-public", AIS_RECENT_SECONDS=600,
    AIS_STALE_SECONDS=3600, AIS_HEARTBEAT_TIMEOUT_SECONDS=120, AIS_MAX_TRACK_POINTS=5000,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class VesselCSVTests(TestCase):
    now = datetime(2026, 9, 16, 12, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.enterContext(patch("apps.vessels.views.timezone.now", return_value=self.now))
        User = get_user_model()
        self.admin = User.objects.create_user(username="csv-admin", password="test-pass", role=User.Role.ADMIN)
        self.viewer = User.objects.create_user(username="csv-viewer", password="test-pass", role=User.Role.VIEWER)
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.vessel = Vessel.objects.create(name="EASTERN URSINIA", mmsi="636023616", imo="9698458")
        self.empty = Vessel.objects.create(name="No Fix Yet", mmsi="111222333")
        self.export_url = reverse("vessels:api_export")
        self.import_url = reverse("vessels:api_import")

    def track_url(self, vessel=None):
        return reverse("vessels:api_positions_export", kwargs={"pk": (vessel or self.vessel).pk})

    def add_position(self, minutes_ago, **kwargs):
        values = {
            "vessel": self.vessel, "timestamp": self.now - timedelta(minutes=minutes_ago),
            "latitude": 4.18291, "longitude": 6.81921, "sog": 11.3, "cog": 223.0,
            "heading": 224.0, "navigational_status": 0, "provider": "marinetraffic_report",
        }
        values.update(kwargs)
        return VesselPosition.objects.create(**values)

    def set_latest(self, minutes_ago=8):
        Vessel.objects.filter(pk=self.vessel.pk).update(
            last_seen=self.now - timedelta(minutes=minutes_ago), last_latitude=4.18291,
            last_longitude=6.81921, last_sog=11.3, last_cog=223.0, last_heading=224.0,
            last_navigational_status=0, last_provider="marinetraffic_report", destination="ONNE",
        )

    def body(self, response):
        return b"".join(response.streaming_content).decode("utf-8") if response.streaming else response.content.decode("utf-8")

    def rows(self, response):
        """Header and data rows, past the BOM and the spreadsheet sep= hint."""
        lines = self.body(response).lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[0], "sep=" + csvio.DELIMITER)
        return lines[1:]

    def cells(self, line):
        return line.split(csvio.DELIMITER)

    def upload(self, text, *, dry_run=None, name="report.csv"):
        payload = {"file": SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")}
        if dry_run is not None:
            payload["dry_run"] = dry_run
        return self.client.post(self.import_url, payload, format="multipart")

    # Export ----------------------------------------------------------------

    def test_fleet_export_returns_csv_with_the_agreed_header(self):
        self.set_latest()
        response = self.client.get(self.export_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("fleet-positions-20260916.csv", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        lines = self.rows(response)
        self.assertEqual(lines[0], csvio.DELIMITER.join(csvio.COLUMNS))
        self.assertEqual(len(lines), 3)

    def test_fleet_export_leaves_position_cells_empty_for_a_vessel_without_a_fix(self):
        response = self.client.get(self.export_url)
        rows = {self.cells(line)[0]: self.cells(line) for line in self.rows(response)[1:]}
        # Empty, never 0,0 — the importer rejects 0,0, which would make the template useless.
        self.assertEqual(rows["111222333"][3:5], ["", ""])
        self.assertNotIn("0", rows["111222333"][3] + rows["111222333"][4])

    def test_fleet_export_writes_the_current_fix(self):
        self.set_latest()
        response = self.client.get(self.export_url)
        row = next(self.cells(line) for line in self.rows(response) if line.startswith("636023616"))
        self.assertEqual(row[3], "4.18291")
        self.assertEqual(row[4], "6.81921")
        self.assertEqual(row[9], "2026-09-16T11:52:00Z")

    def test_track_export_lists_stored_observations_chronologically(self):
        self.add_position(30, latitude=4.0)
        self.add_position(10, latitude=4.1)
        response = self.client.get(self.track_url())
        lines = self.rows(response)
        self.assertEqual(lines[0], csvio.DELIMITER.join(csvio.COLUMNS))
        self.assertEqual(len(lines), 3)
        self.assertLess(self.cells(lines[1])[9], self.cells(lines[2])[9])
        self.assertIn("636023616-track-20260916.csv", response["Content-Disposition"])

    def test_track_export_rejects_an_invalid_range(self):
        self.assertEqual(self.client.get(self.track_url(), {"range": "all-time"}).status_code, 400)

    def test_exports_require_authentication(self):
        self.client.logout()
        self.assertIn(self.client.get(self.export_url).status_code, {302, 401, 403})

    def test_viewer_may_export(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.export_url).status_code, 200)

    # Round trip ------------------------------------------------------------

    def test_track_export_reimports_without_a_single_format_error(self):
        self.add_position(30, latitude=4.0)
        self.add_position(10, latitude=4.1)
        text = self.body(self.client.get(self.track_url()))
        result = import_report(text, now=self.now)
        self.assertEqual(result.parsed, 2)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.issues, [])
        # Already stored, so a re-import recognises them rather than duplicating.
        self.assertEqual((result.created, result.duplicates), (0, 2))
        self.assertEqual(VesselPosition.objects.count(), 2)

    def test_filled_in_fleet_template_imports(self):
        template = self.body(self.client.get(self.export_url))
        d = csvio.DELIMITER
        filled = template.replace(
            d.join(["636023616", "9698458", "EASTERN URSINIA"] + [""] * 9),
            d.join(["636023616", "9698458", "EASTERN URSINIA", "4.18291", "6.81921", "11.3",
                    "223.0", "224", "0", "2026-09-16T11:52:00Z", "ONNE", ""]),
        )
        self.assertNotEqual(filled, template)
        result = import_report(filled, now=self.now)
        self.assertEqual(result.created, 1)
        self.vessel.refresh_from_db()
        self.assertAlmostEqual(self.vessel.last_latitude, 4.18291)

    def test_a_name_containing_a_comma_survives_the_round_trip(self):
        Vessel.objects.filter(pk=self.vessel.pk).update(name='OCEAN, STAR "II"')
        self.set_latest()
        result = import_report(self.body(self.client.get(self.export_url)), now=self.now, dry_run=True)
        self.assertEqual(result.parsed, 1)
        self.assertEqual(result.observations[0]["mmsi"], "636023616")

    # Import ----------------------------------------------------------------

    def report(self, timestamp="2026-09-16T11:52:00Z", mmsi="636023616", lat="4.18291", lon="6.81921"):
        return ("MMSI,LAT,LON,SPEED,TIMESTAMP\r\n" + ",".join([mmsi, lat, lon, "11.3", timestamp]) + "\r\n")

    def test_import_stores_positions_and_advances_the_vessel(self):
        response = self.upload(self.report())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["parsed"], data["created"], data["vessels_advanced"]), (1, 1, 1))
        self.assertEqual(data["dry_run"], False)
        self.assertEqual(data["freshest_age_seconds"], 480)  # 8 min, inside AIS_RECENT_SECONDS
        self.assertEqual(data["observations"][0]["status"], "RECENT")
        self.assertEqual(data["observations"][0]["mmsi"], "636023616")
        self.vessel.refresh_from_db()
        self.assertAlmostEqual(self.vessel.last_latitude, 4.18291)
        self.assertEqual(VesselPosition.objects.count(), 1)

    def test_import_marks_a_recent_fix_as_recent(self):
        data = self.upload(self.report(timestamp="2026-09-16T11:58:00Z")).json()
        self.assertEqual(data["freshest_age_seconds"], 120)
        self.assertEqual(data["observations"][0]["status"], "RECENT")

    def test_import_tags_an_older_fix_stale_and_a_weeks_old_one_as_no_recent_ais(self):
        stale = self.upload(self.report(timestamp="2026-09-16T11:00:00Z")).json()
        self.assertEqual(stale["observations"][0]["status"], "STALE")  # 60 min
        old = self.upload(self.report(timestamp="2026-07-31T11:00:00Z", lat="4.75")).json()
        self.assertEqual(old["observations"][0]["status"], "NO_RECENT_AIS")
        self.assertGreater(old["freshest_age_seconds"], 3600)

    def test_dry_run_reports_without_writing(self):
        data = self.upload(self.report(), dry_run="true").json()
        self.assertEqual((data["dry_run"], data["parsed"], data["created"]), (True, 1, 0))
        self.assertEqual(VesselPosition.objects.count(), 0)
        self.vessel.refresh_from_db()
        self.assertIsNone(self.vessel.last_seen)

    def test_import_reports_an_unregistered_mmsi_without_creating_a_vessel(self):
        data = self.upload(self.report(mmsi="999888777")).json()
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["skipped"], 1)
        self.assertTrue(any("not a registered vessel" in issue for issue in data["issues"]))
        self.assertEqual(Vessel.objects.count(), 2)

    def test_import_rejects_an_unusable_file(self):
        response = self.upload("name,port\r\nfoo,bar\r\n")
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())
        self.assertEqual(VesselPosition.objects.count(), 0)

    def test_import_without_a_file_is_a_bad_request(self):
        self.assertEqual(self.client.post(self.import_url, {}, format="multipart").status_code, 400)

    def test_viewer_cannot_import(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.upload(self.report()).status_code, 403)
        self.assertEqual(VesselPosition.objects.count(), 0)

    def test_anonymous_cannot_import(self):
        self.client.logout()
        self.assertIn(self.upload(self.report()).status_code, {302, 401, 403})
        self.assertEqual(VesselPosition.objects.count(), 0)

    def test_reimporting_the_same_upload_creates_no_duplicate(self):
        self.upload(self.report())
        data = self.upload(self.report()).json()
        self.assertEqual((data["created"], data["duplicates"]), (0, 1))
        self.assertEqual(VesselPosition.objects.count(), 1)

    def test_import_never_moves_a_vessel_backwards(self):
        self.upload(self.report(timestamp="2026-09-16T11:52:00Z"))
        data = self.upload(self.report(timestamp="2026-09-16T06:00:00Z", lat="1.0", lon="2.0")).json()
        self.assertEqual((data["created"], data["vessels_advanced"]), (1, 0))
        self.vessel.refresh_from_db()
        self.assertAlmostEqual(self.vessel.last_latitude, 4.18291)

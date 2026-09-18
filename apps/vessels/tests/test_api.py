from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.middleware.csrf import _get_new_csrf_string
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.vessels.models import AISListenerState, Vessel, VesselPosition


@override_settings(
    AISSTREAM_API_KEY="test-backend-key-never-public", AIS_RECENT_SECONDS=600,
    AIS_STALE_SECONDS=3600, AIS_HEARTBEAT_TIMEOUT_SECONDS=120,
    AIS_MAX_ACTIVE_VESSELS=200, AIS_MAX_TRACK_POINTS=5000,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class VesselAPITests(TestCase):
    now = datetime(2026, 9, 15, 12, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.enterContext(patch("apps.vessels.views.timezone.now", return_value=self.now))
        User = get_user_model()
        self.admin = User.objects.create_user(username="vessel-admin", password="test-pass", role=User.Role.ADMIN)
        self.viewer = User.objects.create_user(username="vessel-viewer", password="test-pass", role=User.Role.VIEWER)
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.fleet_url = reverse("vessels:api_vessels")
        self.vessel = Vessel.objects.create(name="Research Vessel", mmsi="123456789", vessel_type="Research")

    def url(self, name, vessel=None):
        return reverse("vessels:" + name, kwargs={"pk": (vessel or self.vessel).pk})

    def position(self, when=None, **kwargs):
        values = {"vessel": self.vessel, "timestamp": when or self.now, "latitude": 4.18291, "longitude": 6.81921}
        values.update(kwargs)
        return VesselPosition.objects.create(**values)

    def set_latest(self, *, age=30):
        Vessel.objects.filter(pk=self.vessel.pk).update(
            last_seen=self.now - timedelta(seconds=age), last_latitude=4.2, last_longitude=6.9,
            last_sog=11.3, last_cog=223, last_heading=None, last_navigational_status=0,
            destination="BONNY (declared)", eta={"month": 9, "day": 16, "hour": 18, "minute": 0}, draught=4.8,
        )

    def test_anonymous_endpoints_are_json_and_do_not_reveal_the_fleet(self):
        self.client.logout()
        for endpoint in (
            self.fleet_url, self.url("api_vessel"), self.url("api_latest"),
            self.url("api_positions"), reverse("vessels:api_status"),
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 403)
                self.assertIn("application/json", response["Content-Type"])
                self.assertIn("detail", response.json())
                self.assertNotIn(self.vessel.mmsi, response.content.decode())
                self.assertIn("no-store", response["Cache-Control"])

    def test_viewer_reads_global_fleet_but_cannot_register_or_modify_tracking(self):
        self.client.force_login(self.viewer)
        response = self.client.get(self.fleet_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["can_manage"])
        self.assertEqual(response.json()["vessels"][0]["mmsi"], self.vessel.mmsi)
        self.assertEqual(self.client.post(self.fleet_url, {"name": "New", "mmsi": "987654321"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(self.url("api_vessel"), {"is_active": False}, format="json").status_code, 403)
        self.vessel.refresh_from_db()
        self.assertTrue(self.vessel.is_active)
        self.assertEqual(Vessel.objects.count(), 1)

    def test_admin_registration_and_stop_tracking_retain_history_and_mmsi_identity(self):
        saved = self.position(self.now - timedelta(minutes=5))
        response = self.client.post(self.fleet_url, {
            "name": "Supply Vessel", "mmsi": "987654321", "imo": "9074729", "vessel_type": "Supply",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["vessel"]["imo"], "9074729")
        self.assertIsNone(response.json()["vessel"]["last_position"])
        self.assertEqual(response.json()["vessel"]["status"], "NO_RECENT_AIS")
        response = self.client.patch(self.url("api_vessel"), {"name": "Renamed", "is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        self.assertFalse(response.json()["vessel"]["is_active"])
        self.assertTrue(VesselPosition.objects.filter(pk=saved.pk).exists())
        history = self.client.get(self.url("api_positions")).json()
        self.assertEqual(history["positions"][0]["id"], saved.pk)
        response = self.client.patch(self.url("api_vessel"), {"mmsi": "123456788"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("mmsi", response.json())
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.mmsi, "123456789")
        self.assertEqual(self.client.delete(self.url("api_vessel")).status_code, 405)

    def test_registration_validates_mmsi_imo_duplicates_and_read_only_ais_fields(self):
        for payload, field in (
            ({"name": "Bad", "mmsi": "123"}, "mmsi"),
            ({"name": "Bad", "mmsi": "１２３４５６７８９"}, "mmsi"),
            ({"name": "Bad", "mmsi": "12345678X"}, "mmsi"),
            ({"name": "Duplicate", "mmsi": self.vessel.mmsi}, "mmsi"),
            ({"name": "Bad", "mmsi": "111222333", "imo": "9074728"}, "imo"),
            ({"name": "", "mmsi": "111222333"}, "name"),
            ({"name": "Bad", "mmsi": "111222333", "last_latitude": 5.0}, "last_latitude"),
            ({"name": "Bad", "mmsi": "111222333", "destination": "INVENTED"}, "destination"),
        ):
            with self.subTest(field=field, payload=payload):
                response = self.client.post(self.fleet_url, payload, format="json")
                self.assertEqual(response.status_code, 400, response.json())
                self.assertIn(field, response.json())
        self.assertEqual(Vessel.objects.count(), 1)

    @override_settings(AIS_MAX_ACTIVE_VESSELS=2)
    def test_active_limit_applies_to_registration_and_reactivation_but_allows_stopping(self):
        Vessel.objects.create(name="Second", mmsi="222222222")
        inactive = Vessel.objects.create(name="Stopped", mmsi="333333333", is_active=False)
        response = self.client.post(self.fleet_url, {"name": "Excess", "mmsi": "444444444"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("2 active vessels", str(response.json()))
        self.assertEqual(self.client.patch(self.url("api_vessel", inactive), {"is_active": True}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.url("api_vessel"), {"name": "Still active"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(self.url("api_vessel"), {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(self.url("api_vessel", inactive), {"is_active": True}, format="json").status_code, 200)
        self.assertEqual(Vessel.objects.filter(is_active=True).count(), 2)

    def test_session_authenticated_writes_require_csrf_token(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        payload = {"name": "CSRF Vessel", "mmsi": "555555555"}
        denied = csrf_client.post(self.fleet_url, payload, format="json")
        self.assertEqual(denied.status_code, 403)
        self.assertIn("CSRF", denied.json()["detail"])
        token = _get_new_csrf_string()
        csrf_client.cookies["csrftoken"] = token
        accepted = csrf_client.post(self.fleet_url, payload, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(accepted.status_code, 201, accepted.json())

    def test_freshness_boundaries_keep_last_real_position_and_declared_eta_without_year(self):
        for age, expected in ((600, "RECENT"), (601, "STALE"), (3600, "STALE"), (3601, "NO_RECENT_AIS")):
            self.set_latest(age=age)
            response = self.client.get(self.url("api_latest"))
            self.assertEqual(response.status_code, 200)
            vessel = response.json()["vessel"]
            self.assertEqual((vessel["status"], vessel["age_seconds"]), (expected, age))
            self.assertEqual((vessel["last_position"]["latitude"], vessel["last_position"]["longitude"]), (4.2, 6.9))
            self.assertIsNone(vessel["last_position"]["heading"])
            self.assertEqual(vessel["last_position"]["source"], "AIS")
            self.assertEqual(vessel["eta"], {"month": 9, "day": 16, "hour": 18, "minute": 0})
            self.assertNotIn("year", vessel["eta"])
        self.assertEqual(VesselPosition.objects.count(), 0)

    def test_history_ranges_are_chronological_and_do_not_insert_the_current_marker(self):
        points = [self.position(self.now - timedelta(days=days)) for days in (31, 29, 6, 2, 0.5)]
        self.set_latest(age=1)
        for period, expected in (("24h", points[4:]), ("7d", points[2:]), ("30d", points[1:])):
            response = self.client.get(self.url("api_positions"), {"range": period})
            self.assertEqual(response.status_code, 200, response.json())
            data = response.json()
            self.assertEqual([point["id"] for point in data["positions"]], [point.pk for point in expected])
            self.assertEqual(data["total_count"], len(expected))
            self.assertFalse(data["simplified"])
            self.assertTrue(all(point["source"] == "AIS" for point in data["positions"]))
        latest = self.client.get(self.url("api_latest")).json()["vessel"]["last_position"]
        self.assertEqual(latest["latitude"], 4.2)
        self.assertNotEqual(latest["latitude"], points[-1].latitude)

    def test_all_history_keeps_old_observations_and_excludes_future_and_other_vessels(self):
        oldest = self.position(self.now - timedelta(days=400))
        latest = self.position(self.now - timedelta(minutes=1), latitude=5.0)
        self.position(self.now + timedelta(days=1))
        other = Vessel.objects.create(name="Other vessel", mmsi="987654321")
        self.position(vessel=other)
        response = self.client.get(self.url("api_positions"), {"range": "all"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["positions"]], [oldest.pk, latest.pk])
        self.assertEqual(response.json()["total_count"], 2)
        exported = self.client.get(self.url("api_positions_export"), {"range": "all"})
        self.assertEqual(exported.status_code, 200)
        self.assertIn(oldest.timestamp.date().isoformat(), exported.content.decode())

    def test_custom_history_validates_timezone_order_range_and_limit(self):
        first = self.position(self.now - timedelta(hours=2))
        self.position(self.now - timedelta(hours=1))
        response = self.client.get(self.url("api_positions"), {
            "range": "custom", "start": "2026-09-15T11:00:00+01:00", "end": "2026-09-15T10:30:00Z",
        })
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual([row["id"] for row in response.json()["positions"]], [first.pk])
        for query in (
            {"range": "custom", "start": "2026-09-15T10:00:00", "end": self.now.isoformat()},
            {"range": "custom", "start": self.now.isoformat(), "end": self.now.isoformat()},
            {"range": "custom", "start": "invalid", "end": self.now.isoformat()},
            {"range": "custom"}, {"range": "invalid"}, {"range": "all", "start": self.now.isoformat()}, {"limit": "1"}, {"limit": "5001"},
            {"limit": "NaN"}, {"range": "24h", "start": self.now.isoformat()},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url("api_positions"), query).status_code, 400)

    def test_database_sampling_returns_bounded_actual_rows_and_preserves_first_last(self):
        points = VesselPosition.objects.bulk_create([
            VesselPosition(vessel=self.vessel, timestamp=self.now - timedelta(minutes=100-index), latitude=4+index/10000, longitude=6)
            for index in range(100)
        ])
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(self.url("api_positions"), {"limit": 7})
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()
        self.assertEqual((data["total_count"], data["returned_count"], data["simplified"]), (100, 7, True))
        expected_ids = [points[index * 99 // 6].pk for index in range(7)]
        self.assertEqual([point["id"] for point in data["positions"]], expected_ids)
        ranked = [query["sql"] for query in captured.captured_queries if "ROW_NUMBER" in query["sql"]]
        self.assertEqual(len(ranked), 1)
        self.assertIn("LIMIT 7", ranked[0])
        self.assertEqual(data["positions"][0]["latitude"], points[0].latitude)
        self.assertEqual(data["positions"][-1]["latitude"], points[-1].latitude)

    def test_duplicate_observation_is_not_repeated_in_history(self):
        observation = self.position()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.position()
        response = self.client.get(self.url("api_positions"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([point["id"] for point in response.json()["positions"]], [observation.pk])

    def test_collection_outage_is_explicit_without_exposing_provider_secrets(self):
        secret = "test-backend-key-never-public"
        AISListenerState.objects.create(
            status="connected", heartbeat_at=self.now - timedelta(seconds=121), last_error_code=secret,
        )
        self.set_latest(age=5)
        response = self.client.get(self.fleet_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["collection"]["status"], "unavailable")
        self.assertEqual(response.json()["collection"]["last_error_code"], "heartbeat_expired")
        self.assertEqual(response.json()["vessels"][0]["last_position"]["latitude"], 4.2)
        self.assertNotIn(secret, response.content.decode())
        AISListenerState.objects.update(heartbeat_at=self.now)
        response = self.client.get(reverse("vessels:api_status"))
        self.assertEqual(response.json()["collection"]["status"], "connected")
        self.assertEqual(response.json()["collection"]["last_error_code"], "")
        self.assertNotIn(secret, response.content.decode())
        with override_settings(AISSTREAM_API_KEY=""):
            response = self.client.get(reverse("vessels:api_status"))
        self.assertFalse(response.json()["collection"]["configured"])
        self.assertEqual(response.json()["collection"]["status"], "not_configured")

    def test_database_outage_returns_json_error_instead_of_an_empty_track(self):
        with patch("apps.vessels.views.Vessel.objects.order_by", side_effect=DatabaseError("secret provider value")):
            response = self.client.get(self.fleet_url)
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", response.json()["detail"])
        self.assertNotIn("secret provider value", response.content.decode())
        self.assertNotIn("vessels", response.json())
        self.assertIn("private", response["Cache-Control"])

    def test_unknown_vessel_is_json_404(self):
        response = self.client.get(reverse("vessels:api_latest", kwargs={"pk": 99999}))
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

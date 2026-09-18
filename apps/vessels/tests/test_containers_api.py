from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient


PAYLOAD = {
    "available": True,
    "containers": [{
        "id": 7, "number": "WEL/RL/002", "owner": "WESTPAQ/UTC", "status": "In transit",
        "location": "—", "open_count": 1, "oldest_days_open": 116,
        "open_shipments": [{
            "id": 54, "report": "TRK-2026-0054", "status": "sent", "status_label": "Sent",
            "origin": "AVEON YARD", "destination": "BONGA", "sent": "23/05/2026 10:00",
            "sent_iso": "2026-05-23T10:00:00+00:00", "days_open": 116, "items": 123, "issues": 0,
        }],
    }],
    "totals": {"containers": 31, "with_open": 5, "open_shipments": 5},
}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class VesselContainersAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username="box-viewer", password="test-pass", role=User.Role.VIEWER)
        self.client = APIClient()
        self.client.force_login(self.viewer)
        self.url = reverse("vessels:api_containers")

    def test_returns_containers_with_their_open_shipments(self):
        with patch("apps.core.tracking_source.map_containers_safe", return_value=PAYLOAD) as source:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        data = response.json()
        self.assertEqual(data["totals"]["open_shipments"], 5)
        container = data["containers"][0]
        self.assertEqual(container["number"], "WEL/RL/002")
        self.assertEqual(container["open_shipments"][0]["report"], "TRK-2026-0054")
        source.assert_called_once_with()

    def test_a_trackfy_outage_degrades_without_leaking_the_reason(self):
        broken = {"available": False, "error": "could not connect to host 10.0.0.9 user=postgres password=hunter2",
                  "containers": [], "totals": {"containers": 0, "with_open": 0, "open_shipments": 0}}
        with patch("apps.core.tracking_source.map_containers_safe", return_value=broken):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertEqual(response.json()["containers"], [])
        self.assertIs(response.json()["available"], False)
        # The upstream message can carry hosts and credentials; it must stay server-side.
        self.assertNotIn("hunter2", body)
        self.assertNotIn("10.0.0.9", body)

    def test_requires_authentication(self):
        self.client.logout()
        with patch("apps.core.tracking_source.map_containers_safe", return_value=PAYLOAD):
            self.assertIn(self.client.get(self.url).status_code, {302, 401, 403})

    def test_a_viewer_may_read_containers(self):
        with patch("apps.core.tracking_source.map_containers_safe", return_value=PAYLOAD):
            self.assertEqual(self.client.get(self.url).status_code, 200)

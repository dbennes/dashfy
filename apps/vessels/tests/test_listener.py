import json
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.vessels.ais import IngestionResult, MESSAGE_TYPES
from apps.vessels.listener import AISStreamListener, SubscriptionError, WorkerLockLost, active_mmsis, build_subscription
from apps.vessels.management.commands.listen_ais import exclusive_worker
from apps.vessels.models import AISListenerState, Vessel


KEY = "test-only-secret-never-log"
MMSI = "123456789"
CONFIRMED = json.dumps({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}).encode()


class StopControl:
    def __init__(self, after_waits=1):
        self.stopped = False
        self.after_waits = after_waits
        self.waits = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        if len(self.waits) >= self.after_waits:
            self.stopped = True
        return self.stopped


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


class Socket:
    def __init__(self, frames, stop, clock=None, step=1):
        self.frames = iter(frames)
        self.stop = stop
        self.clock = clock
        self.step = step
        self.sent = []
        self.events = []

    def __enter__(self):
        self.events.append("connected")
        return self

    def __exit__(self, *args):
        self.events.append("closed")

    def send(self, value):
        self.events.append("subscription")
        self.sent.append(json.loads(value))

    def recv(self, timeout):
        self.events.append("receive")
        if self.clock:
            self.clock.value += self.step
        try:
            return next(self.frames)
        except StopIteration:
            self.stop.set()
            raise TimeoutError()


@override_settings(AISSTREAM_API_KEY=KEY, AIS_MAX_ACTIVE_VESSELS=200,
                   AIS_SUBSCRIPTION_REFRESH_SECONDS=30, AISSTREAM_BOUNDING_BOXES=[[[-90, -180], [90, 180]]])
class AISListenerTests(SimpleTestCase):
    def worker(self, *, stop=None, connect=None, clock=None, **kwargs):
        worker = AISStreamListener(stop_event=stop or StopControl(), connect_factory=connect or Mock(),
                                   clock=clock or Clock(), jitter=lambda _low, _high: 0, **kwargs)
        worker._state = Mock()
        return worker

    def test_subscription_has_compression_compatible_filters_and_never_silently_drops_mmsis(self):
        subscription = build_subscription(["987654321", MMSI, MMSI], KEY)
        self.assertEqual(subscription["FiltersShipMMSI"], [MMSI, "987654321"])
        self.assertEqual(subscription["FilterMessageTypes"], list(MESSAGE_TYPES))
        self.assertEqual(subscription["BoundingBoxes"], [[[-90, -180], [90, 180]]])
        for mmsis, code in (([], "no_active_vessels"), (["123"], "invalid_mmsi"),
                            ([str(100000000 + index) for index in range(201)], "too_many_vessels")):
            with self.subTest(code=code), self.assertRaises(SubscriptionError) as caught:
                build_subscription(mmsis, KEY)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn(KEY, str(caught.exception))
        with override_settings(AISSTREAM_BOUNDING_BOXES=[]), self.assertRaises(SubscriptionError):
            build_subscription([MMSI], KEY)

    @patch("apps.vessels.listener.active_mmsis", return_value=[MMSI])
    @patch("apps.vessels.listener.ingest_ais_message", return_value=IngestionResult(accepted=True, position_updated=True))
    def test_initial_subscription_is_immediate_binary_frames_processed_and_transport_logging_disabled(self, ingest, _fleet):
        stop, clock = StopControl(), Clock()
        socket = Socket([CONFIRMED, b'{"MessageType":"PositionReport"}', b"invalid-json"], stop, clock)
        connect = Mock(return_value=socket)
        worker = self.worker(stop=stop, connect=connect, clock=clock)
        worker.run()
        self.assertEqual(socket.events[:3], ["connected", "subscription", "receive"])
        self.assertEqual(socket.sent[0]["FiltersShipMMSI"], [MMSI])
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["compression"], "deflate")
        self.assertTrue(kwargs["logger"].disabled)
        self.assertFalse(kwargs["logger"].propagate)
        self.assertEqual(ingest.call_count, 1)
        self.assertEqual(ingest.call_args.args[0], {"MessageType": "PositionReport"})
        self.assertIsNotNone(worker.last_message_at)
        self.assertTrue(any(call.kwargs.get("status") == "connected" for call in worker._state.call_args_list))

    @override_settings(AIS_SUBSCRIPTION_REFRESH_SECONDS=2)
    @patch("apps.vessels.listener.ingest_ais_message", return_value=IngestionResult())
    def test_refresh_replaces_filters_and_zero_active_vessels_close_instead_of_subscribing_worldwide(self, _ingest):
        stop, clock = StopControl(), Clock()
        socket = Socket([CONFIRMED, b"{}", CONFIRMED, b"{}", b"{}"], stop, clock)
        connect = Mock(return_value=socket)
        fleets = iter([[MMSI], ["987654321"], [], []])
        with patch("apps.vessels.listener.active_mmsis", side_effect=lambda: next(fleets, [])):
            worker = self.worker(stop=stop, connect=connect, clock=clock)
            worker.run()
        self.assertEqual([item["FiltersShipMMSI"] for item in socket.sent], [[MMSI], ["987654321"]])
        self.assertEqual(connect.call_count, 1)
        self.assertIn("closed", socket.events)
        self.assertTrue(any(call.kwargs.get("status") == "idle" for call in worker._state.call_args_list))

    @patch("apps.vessels.listener.active_mmsis", return_value=[])
    def test_no_registered_vessels_do_not_open_a_connection(self, _fleet):
        connect = Mock()
        worker = self.worker(connect=connect)
        worker.run()
        connect.assert_not_called()
        self.assertTrue(any(call.kwargs.get("last_error_code") == "no_active_vessels" for call in worker._state.call_args_list))

    @patch("apps.vessels.listener.active_mmsis", return_value=[str(100000000 + index) for index in range(201)])
    def test_over_account_limit_is_an_explicit_configuration_error_without_connecting(self, _fleet):
        connect = Mock()
        worker = self.worker(connect=connect)
        with self.assertLogs("apps.vessels.listener", level="WARNING"):
            worker.run()
        connect.assert_not_called()
        worker._state.assert_any_call(status="configuration_error", last_error_code="too_many_vessels")

    @patch("apps.vessels.listener.active_mmsis", return_value=[MMSI])
    def test_network_failures_use_exponential_backoff_without_logging_exception_secrets(self, _fleet):
        connect = Mock(side_effect=OSError("Connection details include " + KEY))
        stop = StopControl(after_waits=3)
        worker = self.worker(stop=stop, connect=connect)
        with self.assertLogs("apps.vessels.listener", level="WARNING") as captured:
            worker.run()
        self.assertEqual(stop.waits, [1, 2, 4])
        self.assertEqual(connect.call_count, 3)
        self.assertNotIn(KEY, "\n".join(captured.output))
        self.assertTrue(all(call.kwargs.get("last_error_code", "") in {"", "connection_error"}
                            for call in worker._state.call_args_list))

    @patch("apps.vessels.listener.active_mmsis", return_value=[MMSI])
    def test_provider_error_payload_and_missing_compression_never_leak_frame_contents(self, _fleet):
        for frame, code in ((json.dumps({"error": "Rejected key " + KEY}), "provider_rejected"),
                            (json.dumps({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": False}}), "compression_required")):
            with self.subTest(code=code):
                stop = StopControl()
                socket = Socket([frame], stop)
                worker = self.worker(stop=stop, connect=Mock(return_value=socket))
                with self.assertLogs("apps.vessels.listener", level="WARNING") as captured:
                    worker.run()
                self.assertNotIn(KEY, "\n".join(captured.output))
                worker._state.assert_any_call(status="reconnecting", last_error_code=code)

    @override_settings(AISSTREAM_API_KEY="")
    @patch("apps.vessels.listener.active_mmsis")
    def test_missing_key_is_configuration_error_and_command_fails_before_network_or_database(self, fleet):
        connect = Mock()
        worker = self.worker(connect=connect)
        with self.assertLogs("apps.vessels.listener", level="WARNING"):
            worker.run()
        fleet.assert_not_called()
        connect.assert_not_called()
        worker._state.assert_called_once_with(status="configuration_error", last_error_code="missing_api_key")
        with self.assertRaisesMessage(CommandError, "Set AISSTREAM_API_KEY"):
            call_command("listen_ais", skip_checks=True)

    def test_lost_exclusive_lock_stops_the_worker(self):
        connect = Mock()
        worker = self.worker(connect=connect, lease_check=lambda: False)
        with self.assertLogs("apps.vessels.listener", level="ERROR"), self.assertRaises(WorkerLockLost):
            worker.run()
        connect.assert_not_called()
        worker._state.assert_any_call(status="stopped", last_error_code="lock_lost")

    @patch("apps.vessels.management.commands.listen_ais.connections")
    def test_postgres_worker_lock_uses_separate_connection_and_closes_it(self, connections):
        database = connections.__getitem__.return_value
        database.vendor = "postgresql"
        dedicated = database.copy.return_value
        dedicated.cursor.return_value.__enter__.return_value.fetchone.return_value = [True]
        dedicated.is_usable.return_value = True
        with exclusive_worker() as check:
            self.assertTrue(check())
        database.copy.assert_called_once_with(alias="ais_worker_lock")
        dedicated.close.assert_called_once()
        cursor = dedicated.cursor.return_value.__enter__.return_value
        self.assertIn("pg_try_advisory_lock", cursor.execute.call_args.args[0])

    @patch("apps.vessels.management.commands.listen_ais.connections")
    def test_second_postgres_worker_is_rejected_without_releasing_first_workers_lock(self, connections):
        database = connections.__getitem__.return_value
        database.vendor = "postgresql"
        dedicated = database.copy.return_value
        dedicated.cursor.return_value.__enter__.return_value.fetchone.return_value = [False]
        with self.assertRaisesMessage(CommandError, "Another AIS listener"):
            with exclusive_worker():
                self.fail("A second worker must not start")
        dedicated.close.assert_called_once()


class AISListenerStateTests(TestCase):
    def test_fleet_filter_and_heartbeat_are_system_records_without_provider_secrets(self):
        Vessel.objects.create(mmsi=MMSI, name="Active")
        Vessel.objects.create(mmsi="987654321", name="Stopped", is_active=False)
        self.assertEqual(active_mmsis(), [MMSI])
        worker = AISStreamListener()
        worker.active_count = 1
        worker.last_message_at = timezone.now()
        worker._state(status="connected", connected_at=timezone.now(), last_error_code="")
        state = AISListenerState.objects.get(provider="aisstream")
        self.assertEqual(state.active_vessel_count, 1)
        self.assertEqual(state.status, "connected")
        self.assertEqual(state.last_message_at, worker.last_message_at)
        self.assertIsNotNone(state.heartbeat_at)
        self.assertNotIn(KEY, repr(state.__dict__))

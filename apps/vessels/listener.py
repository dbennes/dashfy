"""Long-running, server-only AISStream connection with bounded subscriptions."""
from __future__ import annotations

import json
import logging
import math
import random
import threading
import time

from django.conf import settings
from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from .ais import MESSAGE_TYPES, decode_frame, ingest_ais_message, normalize_mmsi
from .models import AISListenerState, Vessel
from .transport import AISConnection


AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
logger = logging.getLogger(__name__)
# websockets DEBUG logs include outgoing frames, which contain the API key.
# A dedicated disabled logger prevents disclosure even under global DEBUG.
_transport_logger = logging.Logger("aisstream.transport", level=logging.CRITICAL + 1)
_transport_logger.disabled = True
_transport_logger.propagate = False


class SubscriptionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class WorkerLockLost(RuntimeError):
    pass


def build_subscription(mmsis: list[str], api_key: str) -> dict:
    if not isinstance(api_key, str) or not api_key.strip():
        raise SubscriptionError("missing_api_key")
    if not mmsis:
        raise SubscriptionError("no_active_vessels")
    if any(normalize_mmsi(value) != value for value in mmsis):
        raise SubscriptionError("invalid_mmsi")
    mmsis = sorted(set(mmsis))
    limit = min(200, max(1, int(getattr(settings, "AIS_MAX_ACTIVE_VESSELS", 200))))
    if len(mmsis) > limit:
        raise SubscriptionError("too_many_vessels")
    boxes = getattr(settings, "AISSTREAM_BOUNDING_BOXES", [[[-90, -180], [90, 180]]])
    if not isinstance(boxes, list) or not boxes:
        raise SubscriptionError("invalid_bounding_boxes")
    for box in boxes:
        if not isinstance(box, list) or len(box) != 2:
            raise SubscriptionError("invalid_bounding_boxes")
        for point in box:
            if not isinstance(point, list) or len(point) != 2:
                raise SubscriptionError("invalid_bounding_boxes")
            for value, maximum in zip(point, (90, 180)):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > maximum:
                    raise SubscriptionError("invalid_bounding_boxes")
    return {"APIKey": api_key, "BoundingBoxes": boxes, "FiltersShipMMSI": mmsis, "FilterMessageTypes": list(MESSAGE_TYPES)}


def active_mmsis() -> list[str]:
    return list(Vessel.objects.filter(is_active=True).order_by("mmsi").values_list("mmsi", flat=True))


class AISStreamListener:
    def __init__(self, *, stop_event=None, connect_factory=None, clock=None, jitter=None, lease_check=None):
        self.stop_event = stop_event or threading.Event()
        self.connect = connect_factory or AISConnection
        self.clock = clock or time.monotonic
        self.jitter = jitter or random.uniform
        self.lease_check = lease_check
        self.last_message_at = None
        self.active_count = 0
        self.refresh_seconds = max(2, float(getattr(settings, "AIS_SUBSCRIPTION_REFRESH_SECONDS", 30)))

    def _check_lease(self):
        if self.lease_check is not None and not self.lease_check():
            raise WorkerLockLost("lock_lost")

    def _state(self, **changes):
        changes.update(heartbeat_at=timezone.now(), active_vessel_count=self.active_count)
        if self.last_message_at is not None:
            changes["last_message_at"] = self.last_message_at
        try:
            AISListenerState.objects.update_or_create(provider="aisstream", defaults=changes)
        except DatabaseError:
            # Error messages may contain connection details; never log them.
            logger.warning("AIS listener state could not be saved (database_error)")
            close_old_connections()

    def _consume(self, socket, mmsis, api_key):
        next_refresh = self.clock() + self.refresh_seconds
        next_heartbeat = self.clock() + 15
        confirmation_deadline = self.clock() + 15
        confirmed = False
        while not self.stop_event.is_set():
            tick = self.clock()
            if tick >= next_refresh:
                self._check_lease()
                close_old_connections()
                updated = active_mmsis()
                self.active_count = len(updated)
                if not updated:
                    return
                if updated != mmsis:
                    subscription = build_subscription(updated, api_key)
                    socket.send(json.dumps(subscription, separators=(",", ":")))
                    mmsis = updated
                    confirmed = False
                    confirmation_deadline = tick + 15
                    self._state(status=AISListenerState.Status.CONNECTING, last_error_code="")
                    logger.info("AIS subscription refreshed for %d vessels", self.active_count)
                next_refresh = tick + self.refresh_seconds
            if tick >= next_heartbeat:
                self._check_lease()
                self._state()
                next_heartbeat = tick + 15
            if not confirmed and tick >= confirmation_deadline:
                raise SubscriptionError("provider_rejected")
            try:
                frame = socket.recv(timeout=1)
            except TimeoutError:
                continue
            envelope = decode_frame(frame)
            if envelope is None:
                continue
            if "error" in envelope or "Error" in envelope:
                raise SubscriptionError("provider_rejected")
            if envelope.get("MessageType") == "SubscriptionConfirmation":
                confirmation = envelope.get("Message")
                if not isinstance(confirmation, dict) or confirmation.get("CompressionEnabled") is not True:
                    raise SubscriptionError("compression_required")
                confirmed = True
                self._state(status=AISListenerState.Status.CONNECTED, connected_at=timezone.now(), last_error_code="")
                logger.info("AIS subscription confirmed for %d vessels", self.active_count)
                continue
            result = ingest_ais_message(envelope)
            if result.accepted:
                self.last_message_at = timezone.now()

    def run(self):
        backoff = 1.0
        keep_configuration_error = False
        try:
            while not self.stop_event.is_set():
                started = self.clock()
                try:
                    self._check_lease()
                    close_old_connections()
                    api_key = getattr(settings, "AISSTREAM_API_KEY", "")
                    if not isinstance(api_key, str) or not api_key.strip():
                        self._state(status=AISListenerState.Status.CONFIGURATION_ERROR, last_error_code="missing_api_key")
                        logger.warning("AIS listener requires a backend API key (missing_api_key)")
                        keep_configuration_error = True
                        return
                    mmsis = active_mmsis()
                    self.active_count = len(mmsis)
                    if not mmsis:
                        self._state(status=AISListenerState.Status.IDLE, last_error_code="no_active_vessels")
                        self.stop_event.wait(self.refresh_seconds)
                        continue
                    # Build and validate before connecting so the first send is
                    # immediate, comfortably within the provider's 3-second limit.
                    subscription = build_subscription(mmsis, api_key)
                    self._state(status=AISListenerState.Status.CONNECTING, last_error_code="")
                    with self.connect(
                        AISSTREAM_URL, compression="deflate", open_timeout=10,
                        ping_interval=20, ping_timeout=20, close_timeout=5,
                        max_size=1_048_576, max_queue=64, logger=_transport_logger,
                    ) as socket:
                        socket.send(json.dumps(subscription, separators=(",", ":")))
                        logger.info("AIS subscription sent for %d vessels", self.active_count)
                        self._consume(socket, mmsis, api_key)
                    backoff = 1.0
                except WorkerLockLost:
                    self._state(status=AISListenerState.Status.STOPPED, last_error_code="lock_lost")
                    logger.error("AIS worker stopped because its exclusive lock was lost (lock_lost)")
                    raise
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    if isinstance(exc, SubscriptionError):
                        code = exc.code
                    elif isinstance(exc, DatabaseError):
                        code = "database_error"
                    else:
                        code = "connection_error"
                    configuration_error = code in {"too_many_vessels", "invalid_mmsi", "invalid_bounding_boxes"}
                    state = AISListenerState.Status.CONFIGURATION_ERROR if configuration_error else AISListenerState.Status.RECONNECTING
                    self._state(status=state, last_error_code=code)
                    if self.clock() - started >= 60:
                        backoff = 1.0
                    delay = self.refresh_seconds if configuration_error else min(60, backoff + self.jitter(0, backoff / 4))
                    logger.warning("AIS connection will retry in %.1f seconds (%s)", delay, code)
                    self.stop_event.wait(delay)
                    backoff = min(60, backoff * 2)
        finally:
            if not keep_configuration_error:
                self._state(status=AISListenerState.Status.STOPPED)

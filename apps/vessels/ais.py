"""Validate AISStream observations and retain real positions on a bounded cadence.

Wire schemas: https://github.com/aisstream/ais-message-models
MetaData's full UTC timestamp is authoritative; AIS Timestamp is only a second
within a minute. Static-message metadata never supplies a new position.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
import json
import math
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Vessel, VesselPosition
from .voyages import accept_destination_change, advance_voyage, destination_observation_is_newer, vessel_voyage_state


POSITION_TYPES = frozenset({"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"})
STATIC_TYPES = frozenset({"ShipStaticData", "StaticDataReport"})
MESSAGE_TYPES = tuple(sorted(POSITION_TYPES | STATIC_TYPES))
_MMSI_RE = re.compile(r"^[0-9]{9}$")


@dataclass(frozen=True)
class AISUpdate:
    mmsi: str
    timestamp: datetime
    message_type: str
    position: dict | None = None
    static_fields: dict = field(default_factory=dict)
    suggested_name: str = ""


@dataclass(frozen=True)
class IngestionResult:
    accepted: bool = False
    position_updated: bool = False
    position_persisted: bool = False
    static_updated: bool = False


def decode_frame(frame) -> dict | None:
    if isinstance(frame, dict):
        return frame
    if not isinstance(frame, (str, bytes)) or len(frame) > 1_048_576:
        return None
    try:
        if isinstance(frame, bytes):
            frame = frame.decode("utf-8")
        value = json.loads(frame)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def normalize_mmsi(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    result = str(value).strip()
    return result if _MMSI_RE.fullmatch(result) else None


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str) or len(value) > 128:
        return None
    text = value.strip()
    explicit_utc = text.endswith(" UTC")
    if explicit_utc:
        text = text[:-4].strip()
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        if not explicit_utc:
            return None
        result = result.replace(tzinfo=dt_timezone.utc)
    try:
        return result.astimezone(dt_timezone.utc)
    except (OverflowError, ValueError):
        return None


def _number(value, minimum: float, maximum: float, *, inclusive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(result) or result < minimum or (result > maximum if inclusive else result >= maximum):
        return None
    return result


def _integer(value, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        return None
    return value


def _text(value, limit: int = 120) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join("".join(char for char in value.replace("@", " ") if char.isprintable()).split())[:limit]


def _eta(value) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {
        "month": _integer(value.get("Month"), 1, 12),
        "day": _integer(value.get("Day"), 1, 31),
        "hour": _integer(value.get("Hour"), 0, 23),
        "minute": _integer(value.get("Minute"), 0, 59),
    }
    if result["month"] and result["day"] and result["day"] > monthrange(2000, result["month"])[1]:
        result["day"] = None
    return result if any(item is not None for item in result.values()) else {}


def _static_fields(message_type: str, body: dict) -> dict:
    result = {}
    data = body
    type_key = "Type"
    if message_type == "StaticDataReport":
        part = body.get("PartNumber")
        if part not in (False, True, 0, 1):
            return result
        data = body.get("ReportB" if part else "ReportA")
        if not isinstance(data, dict) or data.get("Valid") is not True:
            return result
        type_key = "ShipType"
    name = _text(data.get("Name"))
    if name:
        result["name"] = name
    vessel_type = _integer(data.get(type_key), 1, 99)
    if vessel_type is not None:
        result["vessel_type"] = str(vessel_type)
    if message_type == "ShipStaticData":
        imo = _integer(body.get("ImoNumber"), 1_000_000, 9_999_999)
        if imo is not None:
            result["imo"] = str(imo)
        if "Destination" in body:
            result["destination"] = _text(body["Destination"])
        if "Eta" in body:
            result["eta"] = _eta(body["Eta"])
        if "MaximumStaticDraught" in body:
            draught = _number(body["MaximumStaticDraught"], 0, 25.5, inclusive=True)
            result["draught"] = draught if draught else None
    return result


def parse_ais_message(frame, *, now: datetime | None = None) -> AISUpdate | None:
    envelope = decode_frame(frame)
    if not envelope:
        return None
    message_type = envelope.get("MessageType")
    if not isinstance(message_type, str) or message_type not in POSITION_TYPES | STATIC_TYPES:
        return None
    metadata = envelope.get("MetaData")
    messages = envelope.get("Message")
    if not isinstance(metadata, dict) or not isinstance(messages, dict):
        return None
    body = messages.get(message_type)
    if not isinstance(body, dict) or body.get("Valid") is not True:
        return None
    mmsi = normalize_mmsi(metadata.get("MMSI", body.get("UserID")))
    if not mmsi or ("UserID" in body and normalize_mmsi(body["UserID"]) != mmsi):
        return None
    timestamp = _timestamp(metadata.get("time_utc"))
    if timestamp is None or timestamp > (now or timezone.now()) + timedelta(minutes=5):
        return None
    static = _static_fields(message_type, body) if message_type in STATIC_TYPES | {"ExtendedClassBPositionReport"} else {}
    position = None
    if message_type in POSITION_TYPES:
        latitude = _number(body.get("Latitude"), -90, 90, inclusive=True)
        longitude = _number(body.get("Longitude"), -180, 180, inclusive=True)
        if latitude is not None and longitude is not None:
            position = {
                "latitude": latitude, "longitude": longitude,
                "sog": _number(body.get("Sog"), 0, 102.3),
                "cog": _number(body.get("Cog"), 0, 360),
                "heading": _number(body.get("TrueHeading"), 0, 360),
                "navigational_status": _integer(body.get("NavigationalStatus"), 0, 14),
            }
    if position is None and not static:
        return None
    return AISUpdate(mmsi, timestamp, message_type, position, static, _text(metadata.get("ShipName")))


def distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    latitude_delta = lat2 - lat1
    longitude_delta = math.radians(lon2 - lon1)
    arc = math.sin(latitude_delta / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(longitude_delta / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(min(1, max(0, arc))))


def should_persist_position(previous: VesselPosition | None, update: AISUpdate) -> bool:
    if previous is None:
        return True
    elapsed = (update.timestamp - previous.timestamp).total_seconds()
    minimum = max(10, float(getattr(settings, "AIS_POSITION_MIN_SECONDS", 10)))
    if elapsed < minimum:
        return False
    interval = max(minimum, float(getattr(settings, "AIS_POSITION_INTERVAL_SECONDS", 180)))
    if elapsed >= interval:
        return True
    point = update.position
    distance = distance_metres(previous.latitude, previous.longitude, point["latitude"], point["longitude"])
    if distance >= max(1, float(getattr(settings, "AIS_POSITION_DISTANCE_METERS", 250))):
        return True
    if previous.cog is not None and point["cog"] is not None:
        change = abs((point["cog"] - previous.cog + 180) % 360 - 180)
        return change >= max(1, float(getattr(settings, "AIS_POSITION_COURSE_DEGREES", 15)))
    return False


def ingest_ais_message(frame, *, now: datetime | None = None) -> IngestionResult:
    update = parse_ais_message(frame, now=now)
    if update is None:
        return IngestionResult()
    with transaction.atomic():
        vessel = Vessel.objects.select_for_update().filter(mmsi=update.mmsi, is_active=True).first()
        if vessel is None:
            return IngestionResult()
        fields = set()
        static_updated = bool(update.static_fields and (vessel.last_static_seen is None or update.timestamp >= vessel.last_static_seen))
        if static_updated:
            for key, value in update.static_fields.items():
                if key == "destination":
                    continue
                setattr(vessel, key, value)
                fields.add(key)
        if "destination" in update.static_fields and destination_observation_is_newer(vessel, update.timestamp):
            voyage_state = accept_destination_change(
                vessel.voyage_state, previous_destination=vessel.destination,
                destination=update.static_fields["destination"], timestamp=update.timestamp,
            )
            if voyage_state != vessel.voyage_state:
                vessel.voyage_state = voyage_state
                fields.add("voyage_state")
            vessel.destination = update.static_fields["destination"]
            vessel.destination_seen_at = update.timestamp
            fields.update({"destination", "destination_seen_at"})
            destination_updated = True
        else:
            destination_updated = False
        if static_updated:
            vessel.last_static_seen = update.timestamp
            fields.add("last_static_seen")
        position_updated = update.position is not None and (vessel.last_seen is None or update.timestamp > vessel.last_seen)
        persisted = False
        if position_updated:
            vessel.voyage_state = advance_voyage(
                vessel_voyage_state(vessel), latitude=update.position["latitude"],
                longitude=update.position["longitude"], timestamp=update.timestamp,
            )
            fields.add("voyage_state")
            previous = vessel.positions.order_by("-timestamp", "-id").first()
            if should_persist_position(previous, update):
                _position, persisted = VesselPosition.objects.get_or_create(
                    vessel=vessel, timestamp=update.timestamp, defaults={**update.position, "source": "AIS"},
                )
            for key, value in update.position.items():
                setattr(vessel, "last_" + key, value)
                fields.add("last_" + key)
            vessel.last_seen = update.timestamp
            fields.add("last_seen")
        if fields and not vessel.name and update.suggested_name:
            vessel.name = update.suggested_name
            fields.add("name")
        if fields:
            vessel.save(update_fields=sorted(fields | {"updated_at"}))
        return IngestionResult(bool(fields), position_updated, persisted, static_updated or destination_updated)

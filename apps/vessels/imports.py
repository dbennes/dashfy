"""Import real AIS observations from a provider's report export (CSV/TSV).

A provider export carries AIS observations the provider received; this module
only transcribes them. It never estimates, interpolates, backfills or invents a
position, so imported rows keep the same `source="AIS"` guarantee as streamed
ones. `provider` records which channel delivered each row, keeping the origin of
every stored observation auditable.

Column names differ between providers and exports, so headers are matched by
alias. Unparseable rows are reported and skipped, never guessed at.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
import io
import re

from django.db import transaction
from django.utils import timezone

from .ais import distance_metres, normalize_mmsi
from .models import Vessel, VesselPosition
from .voyages import accept_destination_change, advance_voyage, destination_observation_is_newer, vessel_voyage_state


DEFAULT_PROVIDER = "marinetraffic_report"
_PROVIDER_RE = re.compile(r"^[a-z0-9_]{1,32}$")
# AIS "not available" sentinels; a report may pass them through verbatim.
# The 91/181 position sentinels need no check here: parse_coordinate already
# rejects anything outside the valid latitude/longitude range.
_SOG_SENTINEL, _COG_SENTINEL, _HEADING_SENTINEL = 102.3, 360.0, 511.0

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "mmsi": ("mmsi", "shipmmsi", "vesselmmsi"),
    "imo": ("imo", "imonumber", "shipimo"),
    "name": ("shipname", "name", "vesselname", "vessel"),
    "latitude": ("lat", "latitude", "poslat"),
    "longitude": ("lon", "long", "lng", "longitude", "poslon"),
    "timestamp": ("timestamp", "lastpos", "lastposition", "positionreceived", "received",
                  "datetime", "date", "time", "lastreport", "lastknownposition", "postime"),
    "sog": ("speed", "sog", "speedoverground"),
    "cog": ("course", "cog", "courseoverground"),
    "heading": ("heading", "trueheading", "hdg"),
    "navigational_status": ("status", "navstatus", "navigationalstatus"),
    "destination": ("destination", "dest", "nextport"),
}
_HEADER_LOOKUP = {alias: canonical for canonical, aliases in COLUMN_ALIASES.items() for alias in aliases}
_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d %b %Y %H:%M", "%b %d, %Y %H:%M",
    "%d %B %Y %H:%M", "%Y-%m-%d",
)


class ReportError(ValueError):
    """The file could not be read as a position report at all."""


@dataclass
class RowIssue:
    line: int
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        suffix = " (" + self.detail + ")" if self.detail else ""
        return "line " + str(self.line) + ": " + self.reason + suffix


@dataclass
class ImportResult:
    created: int = 0
    duplicates: int = 0
    vessels_advanced: int = 0
    skipped: int = 0
    issues: list[RowIssue] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)

    @property
    def parsed(self) -> int:
        return len(self.observations)


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _clean(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def parse_timestamp(value) -> datetime | None:
    """Accept ISO-8601, common report layouts and epoch seconds; always return UTC."""
    text = _clean(value)
    if not text or text.lower() in {"-", "n/a", "na", "null", "none", "unknown"}:
        return None
    text = re.sub(r"\s*\b(utc|gmt)\b\s*$", "", text, flags=re.IGNORECASE).strip()
    if re.fullmatch(r"\d{9,13}", text):  # epoch seconds or milliseconds
        number = int(text)
        number = number / 1000 if len(text) > 10 else number
        try:
            return datetime.fromtimestamp(number, dt_timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    candidate = None
    try:
        candidate = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for layout in _TIMESTAMP_FORMATS:
            try:
                candidate = datetime.strptime(text, layout)
                break
            except ValueError:
                continue
    if candidate is None:
        return None
    if candidate.tzinfo is None:
        # Reports state UTC in their header rather than per row; AIS is UTC by definition.
        candidate = candidate.replace(tzinfo=dt_timezone.utc)
    try:
        return candidate.astimezone(dt_timezone.utc)
    except (OverflowError, ValueError):
        return None


def parse_coordinate(value, *, limit: float) -> float | None:
    """Decimal degrees, optionally signed or suffixed with a hemisphere letter."""
    text = _clean(value).upper().replace("°", " ")
    if not text:
        return None
    hemisphere = ""
    match = re.search(r"[NSEW]", text)
    if match:
        hemisphere = match.group(0)
        text = re.sub(r"[NSEW]", " ", text)
    text = text.replace(",", ".").strip()
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", text):
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if hemisphere in {"S", "W"}:
        result = -abs(result)
    return result if -limit <= result <= limit else None


def _optional_number(value, *, minimum: float, maximum: float, sentinel: float | None = None) -> float | None:
    text = _clean(value).replace(",", ".")
    text = re.sub(r"(kn|kts|knots|deg)$", "", text, flags=re.IGNORECASE).strip()
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", text or ""):
        return None
    result = float(text)
    if sentinel is not None and result == sentinel:
        return None
    return result if minimum <= result <= maximum else None


def _read_rows(text: str) -> tuple[list[list[str]], dict[str, int]]:
    sample = text[:8192]
    try:
        reader = csv.reader(io.StringIO(text), csv.Sniffer().sniff(sample, delimiters=",;\t|"))
    except csv.Error:
        # csv.excel is a class, so never assign to its attributes: that would rebind
        # the delimiter process-wide and corrupt every later read.
        counts = {candidate: sample.count(candidate) for candidate in ";\t|"}
        best = max(counts, key=counts.get)
        delimiter = best if counts[best] > sample.count(",") else ","
        reader = csv.reader(io.StringIO(text), csv.excel, delimiter=delimiter)
    for raw_header in reader:
        mapping: dict[str, int] = {}
        for index, column in enumerate(raw_header):
            canonical = _HEADER_LOOKUP.get(_normalize_header(column))
            if canonical and canonical not in mapping:
                mapping[canonical] = index
        # Skip provider preamble lines until a row that actually looks like a header.
        if "latitude" in mapping and "longitude" in mapping and ("mmsi" in mapping or "imo" in mapping):
            return list(reader), mapping
        if reader.line_num > 20:
            break
    raise ReportError(
        "No header row with MMSI (or IMO) plus latitude and longitude was found. "
        "Recognised column names: " + ", ".join(sorted(COLUMN_ALIASES)) + "."
    )


def parse_report(text: str, *, now: datetime | None = None) -> ImportResult:
    """Read a report into validated observations without touching the database."""
    if not isinstance(text, str) or not text.strip():
        raise ReportError("The report file is empty.")
    rows, columns = _read_rows(text.lstrip("﻿"))
    now = now or timezone.now()
    horizon = now + timedelta(minutes=5)
    result = ImportResult()

    def cell(row: list[str], key: str) -> str:
        index = columns.get(key)
        return _clean(row[index]) if index is not None and index < len(row) else ""

    for offset, row in enumerate(rows, start=2):
        if not any(_clean(value) for value in row):
            continue
        mmsi = normalize_mmsi(cell(row, "mmsi"))
        imo = cell(row, "imo")
        if not mmsi and not re.fullmatch(r"[0-9]{7}", imo):
            result.skipped += 1
            result.issues.append(RowIssue(offset, "no valid MMSI or IMO", cell(row, "mmsi") or imo))
            continue
        latitude = parse_coordinate(cell(row, "latitude"), limit=90)
        longitude = parse_coordinate(cell(row, "longitude"), limit=180)
        if latitude is None or longitude is None:
            result.skipped += 1
            result.issues.append(RowIssue(offset, "unreadable coordinates",
                                          cell(row, "latitude") + ", " + cell(row, "longitude")))
            continue
        if (latitude, longitude) == (0.0, 0.0):  # exported placeholder for "no position"
            result.skipped += 1
            result.issues.append(RowIssue(offset, "position unavailable in report", "0, 0"))
            continue
        moment = parse_timestamp(cell(row, "timestamp"))
        if moment is None:
            result.skipped += 1
            result.issues.append(RowIssue(offset, "unreadable position timestamp", cell(row, "timestamp")))
            continue
        if moment > horizon:
            result.skipped += 1
            result.issues.append(RowIssue(offset, "timestamp is in the future", moment.isoformat()))
            continue
        result.observations.append({
            "mmsi": mmsi, "imo": imo if re.fullmatch(r"[0-9]{7}", imo) else "",
            "name": cell(row, "name"), "line": offset, "timestamp": moment,
            "latitude": latitude, "longitude": longitude,
            "sog": _optional_number(cell(row, "sog"), minimum=0, maximum=102.2, sentinel=_SOG_SENTINEL),
            "cog": _optional_number(cell(row, "cog"), minimum=0, maximum=359.9, sentinel=_COG_SENTINEL),
            "heading": _optional_number(cell(row, "heading"), minimum=0, maximum=359.9, sentinel=_HEADING_SENTINEL),
            "destination": cell(row, "destination"),
            "age_seconds": max(0, int((now - moment).total_seconds())),
        })
    return result


def _resolve(observation: dict, *, lock: bool = True) -> Vessel | None:
    """Reports never register a vessel; only the existing fleet is updated."""
    queryset = Vessel.objects.select_for_update() if lock else Vessel.objects.all()
    if observation["mmsi"]:
        vessel = queryset.filter(mmsi=observation["mmsi"]).first()
        if vessel is not None:
            return vessel
    if observation["imo"]:
        return queryset.filter(imo=observation["imo"]).first()
    return None


def _unregistered_issue(observation: dict) -> RowIssue:
    return RowIssue(observation["line"], "MMSI/IMO is not a registered vessel",
                    observation["mmsi"] or observation["imo"])


def import_report(text: str, *, provider: str = DEFAULT_PROVIDER, now: datetime | None = None,
                  dry_run: bool = False) -> ImportResult:
    """Store every valid observation. Re-importing the same report changes nothing."""
    provider = _clean(provider).lower().replace("-", "_").replace(" ", "_")
    if not _PROVIDER_RE.fullmatch(provider):
        raise ReportError("Provider must be 1-32 characters of lowercase letters, digits or underscore.")
    result = parse_report(text, now=now)
    if dry_run:
        # Report exactly what a real import would store, including fleet membership.
        registered = []
        for observation in result.observations:
            if _resolve(observation, lock=False) is None:
                result.skipped += 1
                result.issues.append(_unregistered_issue(observation))
            else:
                registered.append(observation)
        result.observations = registered
        return result
    for observation in sorted(result.observations, key=lambda item: item["timestamp"]):
        with transaction.atomic():
            vessel = _resolve(observation)
            if vessel is None:
                result.skipped += 1
                result.issues.append(_unregistered_issue(observation))
                continue
            _position, created = VesselPosition.objects.get_or_create(
                vessel=vessel, timestamp=observation["timestamp"],
                defaults={
                    "latitude": observation["latitude"], "longitude": observation["longitude"],
                    "sog": observation["sog"], "cog": observation["cog"], "heading": observation["heading"],
                    "source": "AIS", "provider": provider,
                },
            )
            result.created += int(created)
            result.duplicates += int(not created)
            # A report may be older than what the live stream already stored.
            if vessel.last_seen is not None and observation["timestamp"] <= vessel.last_seen:
                continue
            destination_updated = bool(observation["destination"] and
                                       destination_observation_is_newer(vessel, observation["timestamp"]))
            vessel.voyage_state = advance_voyage(
                vessel_voyage_state(vessel), latitude=observation["latitude"],
                longitude=observation["longitude"], timestamp=observation["timestamp"],
            )
            fields = {"voyage_state", "last_latitude", "last_longitude", "last_sog", "last_cog", "last_heading",
                      "last_seen", "last_provider", "updated_at"}
            vessel.last_latitude, vessel.last_longitude = observation["latitude"], observation["longitude"]
            vessel.last_sog, vessel.last_cog = observation["sog"], observation["cog"]
            vessel.last_heading, vessel.last_seen = observation["heading"], observation["timestamp"]
            vessel.last_provider = provider
            if destination_updated:
                vessel.voyage_state = accept_destination_change(
                    vessel.voyage_state, previous_destination=vessel.destination,
                    destination=observation["destination"][:120], timestamp=observation["timestamp"],
                )
                vessel.destination = observation["destination"][:120]
                vessel.destination_seen_at = observation["timestamp"]
                fields.update({"destination", "destination_seen_at"})
            if not vessel.name and observation["name"]:
                vessel.name = observation["name"][:120]
                fields.add("name")
            vessel.save(update_fields=sorted(fields))
            result.vessels_advanced += 1
    return result


def movement_summary(vessel: Vessel, observation: dict) -> float | None:
    """Distance from the vessel's stored position to an observation, for review output."""
    if vessel.last_latitude is None or vessel.last_longitude is None:
        return None
    return distance_metres(vessel.last_latitude, vessel.last_longitude,
                           observation["latitude"], observation["longitude"])

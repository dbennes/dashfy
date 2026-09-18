"""The fleet position interchange format, defined once for every export.

A file written here is readable by `imports.py` without editing, so an export
can be filled in or corrected and imported straight back. That round trip is
what constrains the format: numbers are written in plain decimal notation and
timestamps in ISO-8601 UTC because those are the shapes the importer accepts,
and a vessel with no fix exports empty position cells rather than a placeholder
the importer would only have to reject.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone as dt_timezone
import io


COLUMNS = ("MMSI", "IMO", "SHIPNAME", "LAT", "LON", "SPEED", "COURSE", "HEADING",
           "STATUS", "TIMESTAMP", "DESTINATION", "PROVIDER")
DELIMITER = ";"
_COORDINATE_PLACES, _MOTION_PLACES = 6, 1


def format_timestamp(moment: datetime | None) -> str:
    """ISO-8601 UTC with a Z suffix, the one layout every reader of this file agrees on."""
    if moment is None:
        return ""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_number(value, *, places: int) -> str:
    """Fixed decimals without trailing noise; scientific notation would not re-import."""
    if value is None:
        return ""
    text = format(float(value), "." + str(places) + "f")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return text if text.lstrip("+-") else "0"


def _status(value) -> str:
    return "" if value is None else str(int(value))


def vessel_row(vessel) -> list[str]:
    """The vessel's current fix, or a fill-in template row when it has none."""
    positioned = vessel.last_seen is not None and vessel.last_latitude is not None and vessel.last_longitude is not None
    return [
        vessel.mmsi, vessel.imo, vessel.name,
        format_number(vessel.last_latitude, places=_COORDINATE_PLACES) if positioned else "",
        format_number(vessel.last_longitude, places=_COORDINATE_PLACES) if positioned else "",
        format_number(vessel.last_sog, places=_MOTION_PLACES) if positioned else "",
        format_number(vessel.last_cog, places=_MOTION_PLACES) if positioned else "",
        format_number(vessel.last_heading, places=_MOTION_PLACES) if positioned else "",
        _status(vessel.last_navigational_status) if positioned else "",
        format_timestamp(vessel.last_seen) if positioned else "",
        vessel.destination, vessel.last_provider,
    ]


def position_row(vessel, position) -> list[str]:
    """One stored AIS observation, attributed to the provider that delivered it."""
    return [
        vessel.mmsi, vessel.imo, vessel.name,
        format_number(position.latitude, places=_COORDINATE_PLACES),
        format_number(position.longitude, places=_COORDINATE_PLACES),
        format_number(position.sog, places=_MOTION_PLACES),
        format_number(position.cog, places=_MOTION_PLACES),
        format_number(position.heading, places=_MOTION_PLACES),
        _status(position.navigational_status),
        format_timestamp(position.timestamp),
        # Destination is a vessel declaration, not part of the observation; a past
        # fix must not be re-exported carrying the vessel's present destination.
        "", position.provider,
    ]


def render(rows) -> str:
    """One value per spreadsheet column, and still readable by `imports.py`.

    Semicolon-delimited with a leading `sep=` hint because a comma-delimited file
    opens as a single crammed column in locales whose list separator is the
    semicolon. Both the hint line and the BOM are skipped on import: the hint is
    preamble before the header row, so a file edited and saved in a spreadsheet
    re-imports unchanged, including when the spreadsheet rewrites decimals with
    a comma.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, dialect=csv.excel, delimiter=DELIMITER, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return "\ufeff" + "sep=" + DELIMITER + "\r\n" + buffer.getvalue()


def filename(stem: str, *, now: datetime) -> str:
    """UTC-dated name, so a downloaded snapshot says when it was taken."""
    return stem + "-" + now.astimezone(dt_timezone.utc).strftime("%Y%m%d") + ".csv"

"""Versioned Piping fabrication skyline snapshot used below the S03 rundown."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
import logging
import math
from pathlib import Path
from typing import Any

from django.utils import timezone


SKYLINE_DATA_PATH = Path(__file__).resolve().parent / "data" / "fabrication_skyline_20260902.json"
logger = logging.getLogger(__name__)

_EXPECTED_COLUMNS = ["line", "baseline_date", "lookahead_date", "spools"]
_STATUS_KEYS = ("on_time", "late", "partial", "upcoming")
_READINESS_CATEGORIES = ("supports", "erection", "valves")
_READINESS_STATUSES = {"ready", "pending", "partial", "unknown", "not_applicable"}


def _empty_payload(error: str = "") -> dict[str, Any]:
    charts = {
        "dates": [],
        "status_totals": {status: 0 for status in _STATUS_KEYS},
        "status_line_counts": {status: 0 for status in _STATUS_KEYS},
        "material_readiness": {},
    }
    return {
        "available": False,
        "error": error,
        "source": {},
        "kpis": {
            "line_count": 0,
            "entry_count": 0,
            "scope_spools": 0,
            "performed_line_count": 0,
            "performed_spools": 0,
            "remaining_line_count": 0,
            "remaining_spools": 0,
            "upcoming_line_count": 0,
            "upcoming_spools": 0,
            "on_time_line_count": 0,
            "on_time_spools": 0,
            "late_line_count": 0,
            "late_spools": 0,
            "partial_line_count": 0,
            "partial_spools": 0,
            "baseline_last_release_label": "—",
            "lookahead_last_release_label": "—",
            "last_release_variance_days": 0,
        },
        "charts": charts,
        "charts_json": json.dumps(charts, separators=(",", ":")),
    }


def _iso_date(value: Any, *, row_index: int, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"rows[{row_index}].{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"rows[{row_index}].{field} must be an ISO date") from exc


def _positive_integer(value: Any, *, row_index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"rows[{row_index}].spools must be numeric")
    if not math.isfinite(value) or value <= 0 or not float(value).is_integer():
        raise ValueError(f"rows[{row_index}].spools must be a positive integer")
    return int(value)


def _week_ending_friday(value: date) -> date:
    return value + timedelta(days=(4 - value.weekday()) % 7)


def _readiness_category(raw: Any, *, as_of_date: date) -> dict[str, str]:
    """Accept only dated, attributable evidence for an operational light."""
    unknown = {"status": "unknown", "source": "", "as_of_date": "", "note": ""}
    if not isinstance(raw, dict):
        return unknown
    status = raw.get("status")
    if not isinstance(status, str) or status not in _READINESS_STATUSES:
        return unknown
    source = raw.get("source")
    source = source.strip() if isinstance(source, str) else ""
    raw_date = raw.get("as_of_date")
    evidence_date = None
    if isinstance(raw_date, str):
        try:
            parsed_date = date.fromisoformat(raw_date)
            if parsed_date.isoformat() == raw_date and parsed_date <= as_of_date:
                evidence_date = parsed_date
        except ValueError:
            pass
    if status != "unknown" and (not source or evidence_date is None):
        return unknown
    note = raw.get("note")
    return {
        "status": status,
        "source": source,
        "as_of_date": evidence_date.isoformat() if evidence_date else "",
        "note": note.strip() if isinstance(note, str) else "",
    }


def _material_readiness(
    raw: Any,
    rows: list[dict[str, Any]],
    *,
    as_of_date: date,
) -> dict[str, dict[str, dict[str, str]]]:
    """One exact-line lookup, independent of dates, spool progress and filters."""
    readiness = raw if isinstance(raw, dict) else {}
    result = {}
    for line in sorted({row["line"] for row in rows}):
        categories = readiness.get(line)
        categories = categories if isinstance(categories, dict) else {}
        result[line] = {
            category: _readiness_category(categories.get(category), as_of_date=as_of_date)
            for category in _READINESS_CATEGORIES
        }
    return result


def _validated_snapshot(raw: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(raw, dict) or raw.get("schema") != 3:
        raise ValueError("unsupported skyline data schema")
    if raw.get("columns") != _EXPECTED_COLUMNS:
        raise ValueError("unsupported skyline row columns")

    source = raw.get("source")
    if not isinstance(source, dict):
        raise ValueError("skyline source metadata is missing")

    raw_rows = raw.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("skyline rows are missing")
    rows: list[dict[str, Any]] = []
    baseline_by_line: dict[str, date] = {}
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, list) or len(raw_row) != len(_EXPECTED_COLUMNS):
            raise ValueError(f"rows[{index}] must contain four values")
        raw_line, raw_baseline, raw_lookahead, raw_spools = raw_row
        line = str(raw_line).strip() if raw_line is not None else ""
        if not line:
            raise ValueError(f"rows[{index}].line cannot be blank")
        baseline = _iso_date(raw_baseline, row_index=index, field="baseline_date")
        lookahead = _iso_date(
            raw_lookahead,
            row_index=index,
            field="lookahead_date",
        )
        spools = _positive_integer(raw_spools, row_index=index)
        previous_baseline = baseline_by_line.setdefault(line, baseline)
        if previous_baseline != baseline:
            raise ValueError(f"line {line!r} has inconsistent baseline dates")
        rows.append(
            {
                "line": line,
                "baseline": baseline,
                "lookahead": lookahead,
                "spools": spools,
            }
        )
    return dict(source), rows


def _date_segments(
    rows: list[dict[str, Any]],
    *,
    as_of_date: date,
) -> list[dict[str, Any]]:
    rows_by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_line[row["line"]].append(row)

    line_profiles: dict[str, dict[str, Any]] = {}
    for line, line_rows in rows_by_line.items():
        baseline = line_rows[0]["baseline"]
        total_spools = sum(row["spools"] for row in line_rows)
        performed_spools = sum(
            row["spools"] for row in line_rows if row["lookahead"] < as_of_date
        )
        has_upcoming = performed_spools < total_spools
        line_profiles[line] = {
            "total_spools": total_spools,
            "performed_spools": performed_spools,
            "remaining_spools": total_spools - performed_spools,
            "progress_pct": round((performed_spools / total_spools) * 100, 1),
            "has_upcoming": has_upcoming,
            "is_late": (not has_upcoming) and any(
                row["lookahead"] > baseline for row in line_rows
            ),
        }

    forecast_groups: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)
    lookahead_groups: dict[date, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        line = row["line"]
        baseline_bucket = _week_ending_friday(row["baseline"])
        forecast = forecast_groups[baseline_bucket].setdefault(
            line,
            {
                "line": line,
                "date": row["baseline"].isoformat(),
                "spools": 0,
                "dates": [row["baseline"].isoformat()],
            },
        )
        forecast["spools"] += row["spools"]

        profile = line_profiles[line]
        if row["lookahead"] >= as_of_date:
            status = "upcoming"
        elif profile["has_upcoming"]:
            status = "partial"
        elif profile["is_late"]:
            status = "late"
        else:
            status = "on_time"

        lookahead_bucket = _week_ending_friday(row["lookahead"])
        segment = lookahead_groups[lookahead_bucket].setdefault(
            (line, status),
            {
                "line": line,
                "status": status,
                "date": row["lookahead"].isoformat(),
                "spools": 0,
                "performed_spools": 0,
                "remaining_spools": 0,
                "line_spools": profile["total_spools"],
                "line_performed_spools": profile["performed_spools"],
                "line_remaining_spools": profile["remaining_spools"],
                "progress_pct": profile["progress_pct"],
                "dates": [],
            },
        )
        segment["spools"] += row["spools"]
        if row["lookahead"] < as_of_date:
            segment["performed_spools"] += row["spools"]
        else:
            segment["remaining_spools"] += row["spools"]
        segment["dates"].append(row["lookahead"].isoformat())

    dates: list[dict[str, Any]] = []
    for current in sorted(set(forecast_groups) | set(lookahead_groups)):
        forecast = sorted(
            forecast_groups.get(current, {}).values(),
            key=lambda item: item["line"],
        )
        lookahead = sorted(
            lookahead_groups.get(current, {}).values(),
            key=lambda item: (item["line"], item["status"]),
        )
        for segment in lookahead:
            segment["dates"] = sorted(set(segment["dates"]))
            segment["date"] = segment["dates"][0]
        dates.append(
            {
                "date": current.isoformat(),
                "forecast_total": sum(item["spools"] for item in forecast),
                "lookahead_total": sum(item["spools"] for item in lookahead),
                "performed_total": sum(item["performed_spools"] for item in lookahead),
                "remaining_total": sum(item["remaining_spools"] for item in lookahead),
                "forecast": forecast,
                "lookahead": lookahead,
            }
        )
    return dates


def fabrication_skyline(*, as_of_date: date | None = None) -> dict[str, Any]:
    raw = json.loads(SKYLINE_DATA_PATH.read_text(encoding="utf-8"))
    source, rows = _validated_snapshot(raw)
    as_of_date = as_of_date or timezone.localdate()
    try:
        snapshot_date = date.fromisoformat(source["snapshot_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("skyline snapshot date is invalid") from exc
    dates = _date_segments(rows, as_of_date=as_of_date)
    scope_spools = sum(row["spools"] for row in rows)
    line_count = len({row["line"] for row in rows})
    performed_line_count = len({row["line"] for row in rows if row["lookahead"] < as_of_date})
    performed_spools = sum(row["spools"] for row in rows if row["lookahead"] < as_of_date)
    remaining_line_count = len({row["line"] for row in rows if row["lookahead"] >= as_of_date})
    remaining_spools = sum(row["spools"] for row in rows if row["lookahead"] >= as_of_date)
    baseline_last_release = max(row["baseline"] for row in rows)
    lookahead_last_release = max(row["lookahead"] for row in rows)

    status_totals = {status: 0 for status in _STATUS_KEYS}
    status_lines = {status: set() for status in _STATUS_KEYS}
    for date_bucket in dates:
        for segment in date_bucket["lookahead"]:
            status = segment["status"]
            status_totals[status] += segment["spools"]
            status_lines[status].add(segment["line"])
    status_line_counts = {
        status: len(lines)
        for status, lines in status_lines.items()
    }
    charts = {
        "dates": dates,
        "status_totals": status_totals,
        "status_line_counts": status_line_counts,
        "material_readiness": _material_readiness(
            raw.get("material_readiness"), rows, as_of_date=as_of_date
        ),
    }
    source["snapshot_label"] = snapshot_date.strftime("%d %b %y")
    source["as_of_date"] = as_of_date.isoformat()
    source["as_of_label"] = as_of_date.strftime("%d %b %y")

    if sum(date_bucket["forecast_total"] for date_bucket in dates) != scope_spools:
        raise ValueError("forecast skyline does not reconcile with the spool scope")
    if sum(date_bucket["lookahead_total"] for date_bucket in dates) != scope_spools:
        raise ValueError("lookahead skyline does not reconcile with the spool scope")
    if sum(status_totals.values()) != scope_spools:
        raise ValueError("lookahead statuses do not reconcile with the spool scope")
    if performed_spools + remaining_spools != scope_spools:
        raise ValueError("performed and remaining spools do not reconcile with the spool scope")

    return {
        "available": True,
        "error": "",
        "source": source,
        "kpis": {
            "line_count": line_count,
            "entry_count": len(rows),
            "scope_spools": scope_spools,
            "performed_line_count": performed_line_count,
            "performed_spools": performed_spools,
            "remaining_line_count": remaining_line_count,
            "remaining_spools": remaining_spools,
            "upcoming_line_count": status_line_counts["upcoming"],
            "upcoming_spools": status_totals["upcoming"],
            "on_time_line_count": status_line_counts["on_time"],
            "on_time_spools": status_totals["on_time"],
            "late_line_count": status_line_counts["late"],
            "late_spools": status_totals["late"],
            "partial_line_count": status_line_counts["partial"],
            "partial_spools": status_totals["partial"],
            "baseline_last_release_label": baseline_last_release.strftime("%d %b %y"),
            "lookahead_last_release_label": lookahead_last_release.strftime("%d %b %y"),
            "last_release_variance_days": (lookahead_last_release - baseline_last_release).days,
        },
        "charts": charts,
        "charts_json": json.dumps(charts, separators=(",", ":")),
    }


def attach_live_material_readiness(payload: dict[str, Any]) -> None:
    """Enrich the existing cockpit from DATAFY, independently of schedule dates."""
    if not payload.get("available"):
        return
    from apps.core.skyline_material_source import skyline_material_readiness

    charts = payload["charts"]
    lines = sorted({
        segment["line"]
        for bucket in charts["dates"]
        for scenario in ("forecast", "lookahead")
        for segment in bucket[scenario]
    })
    as_of_date = date.fromisoformat(payload["source"]["as_of_date"])
    try:
        readiness = skyline_material_readiness(lines, as_of_date=as_of_date)
    except Exception:
        logger.exception("Unable to read Skyline material availability from DATAFY")
        readiness = {
            line: {
                category: {
                    "status": "unknown", "source": "DATAFY", "as_of_date": "",
                    "note": "DATAFY is temporarily unavailable; availability could not be checked.",
                }
                for category in _READINESS_CATEGORIES
            }
            for line in lines
        }
        payload["source"]["material_readiness_available"] = False
        payload["source"]["material_readiness_label"] = "DATAFY unavailable · material status could not be refreshed"
    else:
        payload["source"]["material_readiness_available"] = True
        payload["source"]["material_readiness_label"] = "DATAFY · support status and material availability"
    charts["material_readiness"] = readiness
    payload["charts_json"] = json.dumps(charts, separators=(",", ":"))


def fabrication_skyline_safe() -> dict[str, Any]:
    """Keep a malformed or missing skyline snapshot from breaking S03."""
    try:
        return fabrication_skyline()
    except Exception:  # pragma: no cover - defensive runtime fallback
        logger.exception("Unable to load the fabrication skyline snapshot")
        return _empty_payload("the source snapshot could not be read.")

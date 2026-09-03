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


def _empty_payload(error: str = "") -> dict[str, Any]:
    charts = {
        "weeks": [],
        "status_totals": {status: 0 for status in _STATUS_KEYS},
        "status_line_counts": {status: 0 for status in _STATUS_KEYS},
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


def _weekly_segments(
    rows: list[dict[str, Any]],
    *,
    as_of_date: date,
) -> list[dict[str, Any]]:
    forecast_groups: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)
    lookahead_groups: dict[date, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)

    line_profiles: dict[str, dict[str, bool]] = {}
    rows_by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_line[row["line"]].append(row)
    for line, line_rows in rows_by_line.items():
        has_past = any(row["lookahead"] < as_of_date for row in line_rows)
        has_upcoming = any(row["lookahead"] >= as_of_date for row in line_rows)
        line_profiles[line] = {
            "has_past": has_past,
            "has_upcoming": has_upcoming,
            "is_late": (not has_upcoming) and any(
                row["lookahead"] > row["baseline"] for row in line_rows
            ),
        }

    for row in rows:
        line = row["line"]
        baseline_week = _week_ending_friday(row["baseline"])
        baseline_segment = forecast_groups[baseline_week].setdefault(
            line,
            {
                "line": line,
                "spools": 0,
                "dates": [row["baseline"].isoformat()],
            },
        )
        baseline_segment["spools"] += row["spools"]

        profile = line_profiles[line]
        if row["lookahead"] >= as_of_date:
            status = "upcoming"
        elif profile["has_past"] and profile["has_upcoming"]:
            status = "partial"
        elif profile["is_late"]:
            status = "late"
        else:
            status = "on_time"

        lookahead_week = _week_ending_friday(row["lookahead"])
        lookahead_segment = lookahead_groups[lookahead_week].setdefault(
            (line, status),
            {
                "line": line,
                "status": status,
                "spools": 0,
                "dates": [],
            },
        )
        lookahead_segment["spools"] += row["spools"]
        lookahead_segment["dates"].append(row["lookahead"].isoformat())
    all_weeks = set(forecast_groups) | set(lookahead_groups)
    first_week = min(all_weeks)
    last_week = max(all_weeks)
    weeks: list[dict[str, Any]] = []
    current = first_week
    while current <= last_week:
        forecast = sorted(forecast_groups.get(current, {}).values(), key=lambda item: item["line"])
        lookahead = sorted(
            lookahead_groups.get(current, {}).values(),
            key=lambda item: (item["line"], item["status"]),
        )
        for segment in lookahead:
            segment["dates"] = sorted(set(segment["dates"]))
        weeks.append(
            {
                "date": current.isoformat(),
                "forecast_total": sum(item["spools"] for item in forecast),
                "lookahead_total": sum(item["spools"] for item in lookahead),
                "forecast": forecast,
                "lookahead": lookahead,
            }
        )
        current += timedelta(days=7)
    return weeks


def fabrication_skyline(*, as_of_date: date | None = None) -> dict[str, Any]:
    raw = json.loads(SKYLINE_DATA_PATH.read_text(encoding="utf-8"))
    source, rows = _validated_snapshot(raw)
    as_of_date = as_of_date or timezone.localdate()
    try:
        snapshot_date = date.fromisoformat(source["snapshot_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("skyline snapshot date is invalid") from exc
    weeks = _weekly_segments(rows, as_of_date=as_of_date)
    scope_spools = sum(row["spools"] for row in rows)
    line_count = len({row["line"] for row in rows})
    performed_line_count = len({row["line"] for row in rows if row["lookahead"] < as_of_date})
    performed_spools = sum(row["spools"] for row in rows if row["lookahead"] < as_of_date)
    upcoming_line_count = len({row["line"] for row in rows if row["lookahead"] >= as_of_date})
    upcoming_spools = sum(row["spools"] for row in rows if row["lookahead"] >= as_of_date)
    baseline_last_release = max(row["baseline"] for row in rows)
    lookahead_last_release = max(row["lookahead"] for row in rows)

    status_totals = {status: 0 for status in _STATUS_KEYS}
    status_lines = {status: set() for status in _STATUS_KEYS}
    for week in weeks:
        for segment in week["lookahead"]:
            status = segment["status"]
            status_totals[status] += segment["spools"]
            status_lines[status].add(segment["line"])
    status_line_counts = {
        status: len(lines)
        for status, lines in status_lines.items()
    }
    charts = {
        "weeks": weeks,
        "status_totals": status_totals,
        "status_line_counts": status_line_counts,
    }
    source["snapshot_label"] = snapshot_date.strftime("%d %b %y")
    source["as_of_date"] = as_of_date.isoformat()
    source["as_of_label"] = as_of_date.strftime("%d %b %y")

    if sum(week["forecast_total"] for week in weeks) != scope_spools:
        raise ValueError("forecast skyline does not reconcile with the spool scope")
    if sum(week["lookahead_total"] for week in weeks) != scope_spools:
        raise ValueError("lookahead skyline does not reconcile with the spool scope")
    if sum(status_totals.values()) != scope_spools:
        raise ValueError("lookahead statuses do not reconcile with the spool scope")
    if performed_spools + upcoming_spools != scope_spools:
        raise ValueError("performed and upcoming spools do not reconcile with the spool scope")

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
            "upcoming_line_count": upcoming_line_count,
            "upcoming_spools": upcoming_spools,
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


def fabrication_skyline_safe() -> dict[str, Any]:
    """Keep a malformed or missing skyline snapshot from breaking S03."""
    try:
        return fabrication_skyline()
    except Exception:  # pragma: no cover - defensive runtime fallback
        logger.exception("Unable to load the fabrication skyline snapshot")
        return _empty_payload("the source snapshot could not be read.")

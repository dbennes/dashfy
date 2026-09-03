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

_EXPECTED_COLUMNS = ["line", "baseline_date", "line_lookahead_date", "spools"]


def _empty_payload(error: str = "") -> dict[str, Any]:
    charts = {"weeks": []}
    return {
        "available": False,
        "error": error,
        "source": {},
        "kpis": {
            "line_count": 0,
            "entry_count": 0,
            "scope_spools": 0,
            "actual_line_count": 0,
            "actual_spools": 0,
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
    if not isinstance(raw, dict) or raw.get("schema") != 2:
        raise ValueError("unsupported skyline data schema")
    if raw.get("columns") != _EXPECTED_COLUMNS:
        raise ValueError("unsupported skyline row columns")

    source = raw.get("source")
    if not isinstance(source, dict):
        raise ValueError("skyline source metadata is missing")

    raw_rows = raw.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("skyline rows are missing")
    raw_actual_dates = raw.get("actual_dates")
    if not isinstance(raw_actual_dates, list) or len(raw_actual_dates) != len(raw_rows):
        raise ValueError("skyline actual dates must align with every row")

    rows: list[dict[str, Any]] = []
    baseline_by_line: dict[str, date] = {}
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, list) or len(raw_row) != len(_EXPECTED_COLUMNS):
            raise ValueError(f"rows[{index}] must contain four values")
        raw_line, raw_baseline, raw_line_lookahead, raw_spools = raw_row
        line = str(raw_line).strip() if raw_line is not None else ""
        if not line:
            raise ValueError(f"rows[{index}].line cannot be blank")
        baseline = _iso_date(raw_baseline, row_index=index, field="baseline_date")
        line_lookahead = _iso_date(
            raw_line_lookahead,
            row_index=index,
            field="line_lookahead_date",
        )
        actual = _iso_date(raw_actual_dates[index], row_index=index, field="actual_date")
        # This versioned snapshot was paired ordinally with Runddown F:G and
        # independently reconciled at +4 calendar days for all 175 records.
        # Fail closed if either parallel sequence is later reordered alone.
        if actual != line_lookahead + timedelta(days=4):
            raise ValueError(f"rows[{index}].actual_date no longer matches Runddown F:G")
        spools = _positive_integer(raw_spools, row_index=index)
        previous_baseline = baseline_by_line.setdefault(line, baseline)
        if previous_baseline != baseline:
            raise ValueError(f"line {line!r} has inconsistent baseline dates")
        rows.append(
            {
                "line": line,
                "baseline": baseline,
                "line_lookahead": line_lookahead,
                "actual": actual,
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
    actual_groups: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)

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

        # Runddown F:G carries the complete 60-day lookahead, including future
        # dates. Per the temporary business rule, only dates strictly before
        # the application date belong in the lower (Actual) band.
        if row["actual"] >= as_of_date:
            continue
        actual_week = _week_ending_friday(row["actual"])
        actual_segment = actual_groups[actual_week].setdefault(
            line,
            {
                "line": line,
                "spools": 0,
                "dates": [],
            },
        )
        actual_segment["spools"] += row["spools"]
        actual_segment["dates"].append(row["actual"].isoformat())
    all_weeks = set(forecast_groups) | set(actual_groups)
    first_week = min(all_weeks)
    last_week = max(all_weeks)
    weeks: list[dict[str, Any]] = []
    current = first_week
    while current <= last_week:
        forecast = sorted(forecast_groups.get(current, {}).values(), key=lambda item: item["line"])
        actual = sorted(actual_groups.get(current, {}).values(), key=lambda item: item["line"])
        for segment in actual:
            segment["dates"] = sorted(set(segment["dates"]))
        weeks.append(
            {
                "date": current.isoformat(),
                "forecast_total": sum(item["spools"] for item in forecast),
                "actual_total": sum(item["spools"] for item in actual),
                "forecast": forecast,
                "actual": actual,
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
    actual_line_count = len({
        row["line"] for row in rows
        if row["actual"] < as_of_date
    })
    actual_spools = sum(
        row["spools"] for row in rows
        if row["actual"] < as_of_date
    )
    baseline_last_release = max(row["baseline"] for row in rows)
    lookahead_last_release = max(row["actual"] for row in rows)
    charts = {"weeks": weeks}
    source["snapshot_label"] = snapshot_date.strftime("%d %b %y")
    source["as_of_date"] = as_of_date.isoformat()
    source["as_of_label"] = as_of_date.strftime("%d %b %y")

    if sum(week["forecast_total"] for week in weeks) != scope_spools:
        raise ValueError("forecast skyline does not reconcile with the spool scope")
    if sum(week["actual_total"] for week in weeks) != actual_spools:
        raise ValueError("actual skyline does not reconcile with the as-of date")

    return {
        "available": True,
        "error": "",
        "source": source,
        "kpis": {
            "line_count": line_count,
            "entry_count": len(rows),
            "scope_spools": scope_spools,
            "actual_line_count": actual_line_count,
            "actual_spools": actual_spools,
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

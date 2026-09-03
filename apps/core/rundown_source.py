"""Versioned Piping ISO rundown snapshot used below S03 Fabrication.

The source workbook is an exported DATAFY material-requisition report.  Only
the cached values from ``Runddown!T1:X75`` are kept in the repository, so the
dashboard does not depend on a user's Downloads folder or on Excel at runtime.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from pathlib import Path
from typing import Any


RUNDOWN_DATA_PATH = Path(__file__).resolve().parent / "data" / "fabrication_rundown_20260902.json"
logger = logging.getLogger(__name__)

_SERIES_KEYS = (
    "dates",
    "lookahead_total",
    "lookahead_rundown",
    "baseline_total",
    "baseline_rundown",
)


def _empty_payload(error: str = "") -> dict[str, Any]:
    charts = {key: [] for key in _SERIES_KEYS}
    return {
        "available": False,
        "error": error,
        "source": {},
        "kpis": {
            "scope_total": 0,
            "baseline_finish_label": "—",
            "lookahead_finish_label": "—",
            "finish_variance_days": 0,
        },
        "charts": charts,
        "charts_json": json.dumps(charts),
    }


def _number_or_none(value: Any, *, key: str, index: int) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key}[{index}] must be numeric or null")
    if not math.isfinite(value) or value < 0 or not float(value).is_integer():
        raise ValueError(f"{key}[{index}] must be a finite non-negative integer")
    return int(value)


def _validate_rundown_pair(
    daily: list[int | float | None],
    remaining: list[int | float | None],
    *,
    key: str,
) -> None:
    first_blank = next((index for index, value in enumerate(remaining) if value is None), len(remaining))
    if first_blank == 0:
        raise ValueError(f"{key} rundown cannot start blank")
    if any(value is None for value in daily[:first_blank]):
        raise ValueError(f"{key} daily series has a blank before its finish")
    if any(value is not None for value in daily[first_blank:]):
        raise ValueError(f"{key} daily series must stay blank after its finish")
    if any(value is not None for value in remaining[first_blank:]):
        raise ValueError(f"{key} rundown must stay blank after its finish")

    active_daily = daily[:first_blank]
    active_remaining = remaining[:first_blank]
    for index in range(1, first_blank):
        expected = active_remaining[index - 1] - active_daily[index - 1]
        if active_remaining[index] != expected:
            raise ValueError(f"{key} rundown does not reconcile at point {index}")
    if active_remaining[-1] != 0:
        raise ValueError(f"{key} rundown must finish at zero")


def _validated_snapshot(raw: Any) -> tuple[dict[str, Any], list[date]]:
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise ValueError("unsupported rundown data schema")

    charts: dict[str, Any] = {}
    raw_dates = raw.get("dates")
    if not isinstance(raw_dates, list) or not raw_dates:
        raise ValueError("rundown dates are missing")

    parsed_dates: list[date] = []
    for index, value in enumerate(raw_dates):
        try:
            parsed_dates.append(date.fromisoformat(str(value)))
        except ValueError as exc:
            raise ValueError(f"dates[{index}] is not an ISO date") from exc
    if parsed_dates != sorted(set(parsed_dates)):
        raise ValueError("rundown dates must be unique and ascending")
    charts["dates"] = [value.isoformat() for value in parsed_dates]

    expected_length = len(parsed_dates)
    for key in _SERIES_KEYS[1:]:
        values = raw.get(key)
        if not isinstance(values, list) or len(values) != expected_length:
            raise ValueError(f"{key} must contain {expected_length} points")
        charts[key] = [
            _number_or_none(value, key=key, index=index)
            for index, value in enumerate(values)
        ]

    scope_total = charts["lookahead_rundown"][0]
    baseline_scope = charts["baseline_rundown"][0]
    lookahead_daily_total = sum(value or 0 for value in charts["lookahead_total"])
    baseline_daily_total = sum(value or 0 for value in charts["baseline_total"])
    if not scope_total or scope_total != baseline_scope:
        raise ValueError("lookahead and baseline must start with the same scope")
    if lookahead_daily_total != scope_total or baseline_daily_total != scope_total:
        raise ValueError("daily totals do not reconcile with rundown scope")
    _validate_rundown_pair(
        charts["lookahead_total"],
        charts["lookahead_rundown"],
        key="lookahead",
    )
    _validate_rundown_pair(
        charts["baseline_total"],
        charts["baseline_rundown"],
        key="baseline",
    )

    source = raw.get("source")
    if not isinstance(source, dict):
        raise ValueError("rundown source metadata is missing")
    return {"source": source, "charts": charts}, parsed_dates


def _first_zero_date(dates: list[date], values: list[int | float | None]) -> date | None:
    return next((point_date for point_date, value in zip(dates, values) if value == 0), None)


def fabrication_rundown() -> dict[str, Any]:
    raw = json.loads(RUNDOWN_DATA_PATH.read_text(encoding="utf-8"))
    snapshot, parsed_dates = _validated_snapshot(raw)
    charts = snapshot["charts"]
    source = dict(snapshot["source"])
    try:
        source["snapshot_label"] = date.fromisoformat(source["snapshot_date"]).strftime("%d %b %y")
    except (KeyError, TypeError, ValueError):
        source["snapshot_label"] = "—"
    baseline_finish = _first_zero_date(parsed_dates, charts["baseline_rundown"])
    lookahead_finish = _first_zero_date(parsed_dates, charts["lookahead_rundown"])
    finish_variance = (
        (lookahead_finish - baseline_finish).days
        if baseline_finish and lookahead_finish
        else 0
    )

    return {
        "available": True,
        "error": "",
        "source": source,
        "kpis": {
            "scope_total": charts["lookahead_rundown"][0],
            "baseline_finish_label": baseline_finish.strftime("%d %b %y") if baseline_finish else "—",
            "lookahead_finish_label": lookahead_finish.strftime("%d %b %y") if lookahead_finish else "—",
            "finish_variance_days": finish_variance,
        },
        "charts": charts,
        "charts_json": json.dumps(charts, separators=(",", ":")),
    }


def fabrication_rundown_safe() -> dict[str, Any]:
    """Keep a malformed or missing snapshot from breaking the cockpit."""
    try:
        return fabrication_rundown()
    except Exception:  # pragma: no cover - defensive runtime fallback
        logger.exception("Unable to load the fabrication rundown snapshot")
        return _empty_payload("the source snapshot could not be read.")

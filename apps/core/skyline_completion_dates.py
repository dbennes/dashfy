"""Stable, explicitly estimated completion dates from weekly observations.

This module uses only the standard library so the read-only DASHFY consumer
can use the same algorithm. Estimated dates never replace actual finish data.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Iterable, Mapping


FABRICATION_STAGE_KEYS = (
    "prefabrication", "fitup", "welding", "ndt", "pwht", "final_ndt",
    "hydrotest", "painting",
)
_COMPLETE_TOLERANCE = Decimal("0.000000001")
_METHODS = {"planned_within_reporting_period", "distributed_within_reporting_period"}


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _percentage(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and 0 <= result <= 100 else None


def _complete(value: Decimal) -> bool:
    return Decimal("100") - value <= _COMPLETE_TOLERANCE


def fabrication_planned_finish(stages: Mapping[str, Any] | None) -> date | None:
    """Latest finish of the scheduled fabrication stages, including painting.

    A scheduled stage without a valid finish makes the result unknown. The
    package envelope is not used because it may include unrelated work.
    """
    if not isinstance(stages, Mapping):
        return None
    scheduled = [
        stages[key]
        for key in FABRICATION_STAGE_KEYS
        if isinstance(stages.get(key), Mapping)
        and ("plan_finish" in stages[key] or stages[key].get("acts"))
    ]
    finishes = [_date(stage.get("plan_finish")) for stage in scheduled]
    return max(finishes) if finishes and all(finishes) else None


def _distributed_date(identity: Any, first_complete: date, start: date) -> date:
    seed = f"{identity}|{first_complete.isoformat()}".encode("utf-8")
    offset = int.from_bytes(sha256(seed).digest(), "big") % ((first_complete - start).days + 1)
    return start + timedelta(days=offset)


def _stored_record(
    value: Any, *, identity: Any, start: date, end: date,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    if type(value.get("schema")) is not int or value.get("schema") != 1:
        return {}
    method = value.get("method")
    if value.get("date_kind") != "estimated" or not isinstance(method, str) or method not in _METHODS:
        return {}
    expected_dates = {
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "first_reported_complete_date": end.isoformat(),
    }
    if any(value.get(key) != expected for key, expected in expected_dates.items()):
        return {}
    chosen = _date(value.get("date"))
    if chosen is None or value.get("date") != chosen.isoformat() or not start <= chosen <= end:
        return {}
    planned_raw = value.get("planned_finish_used")
    planned = _date(planned_raw)
    if planned_raw != "" and (planned is None or planned_raw != planned.isoformat()):
        return {}
    if value["method"] == "planned_within_reporting_period":
        if planned != chosen:
            return {}
    elif (
        (planned is not None and start <= planned <= end)
        or chosen != _distributed_date(identity, end, start)
    ):
        return {}
    return deepcopy(dict(value))


def build_completion_record(
    history: Iterable[Mapping[str, Any]], planned_finish: Any, identity: Any, as_of: Any,
) -> dict[str, Any]:
    """Estimate the current uninterrupted episode of reported completion.

    History rows have ``date``, ``pct_exact`` and an optional ``completion``
    record. For corrections on the same date, the last supplied row wins.
    Only nonfuture, valid percentages participate. An invalid percentage on
    a dated observation fails closed instead of recovering an older 100%.
    """
    cutoff = _date(as_of)
    if cutoff is None:
        return {}
    by_date = {}
    for row in history:
        if not isinstance(row, Mapping):
            continue
        observed = _date(row.get("date"))
        if observed is not None and observed <= cutoff:
            by_date[observed] = row
    ordered = [(day, row, _percentage(row.get("pct_exact"))) for day, row in sorted(by_date.items())]
    if not ordered or any(value is None for _day, _row, value in ordered):
        return {}
    if not _complete(ordered[-1][2]):
        return {}

    first_index = len(ordered) - 1
    while first_index > 0 and _complete(ordered[first_index - 1][2]):
        first_index -= 1
    first_complete = ordered[first_index][0]
    start = (
        ordered[first_index - 1][0] + timedelta(days=1)
        if first_index else first_complete - timedelta(days=6)
    )
    for _day, row, _value in reversed(ordered[first_index:]):
        stored = _stored_record(
            row.get("completion"), identity=identity, start=start, end=first_complete,
        )
        if stored:
            return stored

    planned = _date(planned_finish)
    use_plan = planned is not None and start <= planned <= first_complete
    chosen = planned if use_plan else _distributed_date(identity, first_complete, start)
    return {
        "schema": 1,
        "date": chosen.isoformat(),
        "date_kind": "estimated",
        "method": "planned_within_reporting_period" if use_plan else "distributed_within_reporting_period",
        "period_start": start.isoformat(),
        "period_end": first_complete.isoformat(),
        "first_reported_complete_date": first_complete.isoformat(),
        "planned_finish_used": planned.isoformat() if planned else "",
    }

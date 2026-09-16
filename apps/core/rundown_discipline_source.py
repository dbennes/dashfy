"""Discipline choices for Rundown, preserving the original Piping snapshot.

Structural uses the active fabrication packages already imported in DATAFY.
Its incomplete/overlapping weight scope does not establish a tonnage total, so
the curve counts distinct scheduled WBS packages. It contains planned dates
only: a past plan or a current percentage is not a dated actual/forecast curve.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import logging
from typing import Any

from django.utils import timezone

from . import real_sources
from .rundown_source import _empty_payload, fabrication_rundown

logger = logging.getLogger(__name__)

_STRUCTURAL_PACKAGES_SQL = """
select p.id, p.code, p.name, p.discipline, p.document_id, p.drawing_number,
       p.weight_tons, p.plan_finish, p.actual_finish, p.p6_ref,
       i.original_filename as source_workbook, i.imported_at,
       p.latest_import_id
  from fabrication_fabricationpackage p
  left join fabrication_p6import i on i.id = p.latest_import_id
 where p.is_active = true and p.discipline = 'structural'
 order by p.id
"""


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _positive_weight(value: Any) -> Decimal | None:
    try:
        weight = Decimal(str(value))
        return weight if weight.is_finite() and weight > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _piping_payload(payload: dict) -> dict:
    result = deepcopy(payload)
    original_source = result.setdefault("source", {})
    provenance = []
    if original_source.get("worksheet") and original_source.get("range"):
        provenance.append(f'{original_source["worksheet"]}!{original_source["range"]}')
    if original_source.get("reconciled_from"):
        provenance.append("reconciled schedule")
    if original_source.get("snapshot_label") and original_source["snapshot_label"] != "—":
        provenance.append(f'snapshot {original_source["snapshot_label"]}')
    original_source.update({
        "discipline": "piping", "discipline_label": "Piping",
        "title": "Piping ISO rundown (ROS)", "unit": "spools", "unit_label": "spools",
        "baseline_label": "Baseline", "lookahead_label": "Lookahead", "has_lookahead": True,
        "source_label": " · ".join(provenance), "notice": "",
    })
    return result


def structural_rundown(packages: list[dict]) -> dict:
    """Whole structural WBS scope, with missing dates left in the balance."""
    unique = {}
    for package in packages:
        if package.get("discipline") != "structural":
            continue
        pk = package.get("id")
        if pk is None:
            raise ValueError("A structural package is missing its source identity")
        if pk in unique and unique[pk] != package:
            raise ValueError("A structural package has conflicting source rows")
        unique[pk] = package
    packages = list(unique.values())
    payload = _empty_payload()
    source = {
        "discipline": "structural", "discipline_label": "Structural",
        "title": "Structural fabrication rundown", "unit": "packages", "unit_label": "packages",
        "source_label": "DATAFY · imported structural fabrication schedule",
        "baseline_label": "Imported plan", "lookahead_label": "Lookahead", "has_lookahead": False,
        "workbook": "", "snapshot_date": "", "snapshot_label": "—",
        "as_of_date": timezone.localdate().isoformat(),
        "notice": "Planned fabrication finishes from the imported schedule. No structural lookahead or dated actual progress is loaded.",
        "scope_rule": "One unit per distinct active structural fabrication WBS package, including packages without a linked drawing.",
        "unit_reason": "Complete, non-overlapping tonnage is not established for this schedule; the curve uses package counts.",
        "date_rule": "Planned fabrication finish from the imported package schedule, including the final fabrication stage.",
        "balance_rule": "Remaining scope is measured at the start of each day. A planned finish is deducted from the following day's balance.",
        "unscheduled_packages": [], "import_ids": [],
    }
    payload["source"] = source
    scope_total = len(packages)
    weights = [_positive_weight(package.get("weight_tons")) for package in packages]
    document_counts = Counter(package["document_id"] for package in packages if package.get("document_id"))
    payload["kpis"].update({
        "scope_total": scope_total, "package_count": scope_total,
        "scheduled_scope": 0, "unscheduled_scope": 0,
        "missing_weight_count": sum(weight is None for weight in weights),
        "duplicate_drawing_package_count": sum(count for count in document_counts.values() if count > 1),
        "known_weight_tonnes": float(sum((weight for weight in weights if weight is not None), Decimal(0))),
        "baseline_finish_label": "—", "lookahead_finish_label": "—",
        "planned_finish_label": "—", "finish_variance_days": None,
    })
    releases: Counter[date] = Counter()
    workbooks: set[str] = set()
    import_ids: set[int] = set()
    imported_dates: list[date] = []
    for package in packages:
        workbook = str(package.get("source_workbook") or "").strip()
        finish = _date(package.get("plan_finish"))
        reason = ""
        if not workbook:
            reason = "No attributable fabrication schedule import."
        elif finish is None:
            reason = "No planned fabrication finish date."
        if reason:
            source["unscheduled_packages"].append({
                "package_id": package["id"], "code": package.get("code") or "",
                "name": package.get("name") or "", "reason": reason,
            })
            continue
        releases[finish] += 1
        workbooks.add(workbook)
        imported = _date(package.get("imported_at"))
        if imported:
            imported_dates.append(imported)
        if package.get("latest_import_id"):
            import_ids.add(package["latest_import_id"])
    scheduled = sum(releases.values())
    payload["kpis"]["scheduled_scope"] = scheduled
    payload["kpis"]["unscheduled_scope"] = scope_total - scheduled
    source["workbook"] = ", ".join(sorted(workbooks))
    source["import_ids"] = sorted(import_ids)
    if workbooks and all("AVEON" in workbook.upper() for workbook in workbooks):
        source.update({
            "source_label": "DATAFY · AVEON structural fabrication schedule",
            "baseline_label": "AVEON plan",
            "notice": "Planned fabrication finishes from AVEON. No structural lookahead or dated actual progress is loaded.",
        })
    if imported_dates:
        latest = max(imported_dates)
        source.update(snapshot_date=latest.isoformat(), snapshot_label=latest.strftime("%d %b %y"))
    if not releases:
        payload["error"] = "No dated structural fabrication schedule is available."
        payload["charts_json"] = json.dumps(payload["charts"], separators=(",", ":"))
        return payload
    first, last = min(releases), max(releases)
    if (last - first).days > 3660:
        raise ValueError("Structural fabrication dates exceed a ten-year schedule span")
    charts = payload["charts"]
    remaining = scope_total
    point = first
    while point <= last + timedelta(days=1):
        charts["dates"].append(point.isoformat())
        charts["baseline_total"].append(releases[point])
        charts["baseline_rundown"].append(remaining)
        # Null is unavailable evidence, rather than a fabricated zero or an
        # accidental duplicate of the Piping forecast/Structural plan curve.
        charts["lookahead_total"].append(None)
        charts["lookahead_rundown"].append(None)
        remaining -= releases[point]
        point += timedelta(days=1)
    payload["kpis"]["planned_finish_label"] = last.strftime("%d %b %y")
    if remaining == 0:
        payload["kpis"]["baseline_finish_label"] = (last + timedelta(days=1)).strftime("%d %b %y")
    else:
        source["notice"] += f" {remaining} package(s) lack a usable plan date and remain in the balance."
    payload["available"] = True
    payload["error"] = ""
    payload["charts_json"] = json.dumps(charts, separators=(",", ":"))
    return payload


def rundown_disciplines(piping_payload: dict) -> dict[str, dict]:
    with real_sources._datafy_conn() as conn:
        packages = real_sources._rows(conn.cursor(), _STRUCTURAL_PACKAGES_SQL)
    return {"piping": _piping_payload(piping_payload), "structural": structural_rundown(packages)}


def rundown_disciplines_safe(piping_payload: dict) -> dict[str, dict]:
    try:
        return rundown_disciplines(piping_payload)
    except Exception:
        logger.exception("Structural rundown source unavailable")
        structural = structural_rundown([])
        structural["error"] = "The structural fabrication source could not be refreshed."
        return {"piping": _piping_payload(piping_payload), "structural": structural}


_DISCIPLINE_LABELS = {"piping": "Piping", "electrical": "Electrical", "structural": "Structural"}
# Fixed examples remain identical across refreshes and do not inherit dates,
# quantities, or current progress from any operational source.
_INSTALLATION_SAMPLE_START = date(2026, 9, 1)
_INSTALLATION_SAMPLE_AS_OF = date(2026, 9, 15)
# Daily completions build up toward the middle of each example, then taper.
# Enumerate retains the existing (day offset, quantity) fixture contract.
_INSTALLATION_SAMPLES = {
    "piping": {
        "unit": "spools",
        "baseline": tuple(enumerate((
            1, 2, 2, 3, 3, 4, 4, 4, 5, 5, 6, 6,
            7, 7, 7, 8, 8, 9, 9, 9, 9, 7, 7, 6,
            6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1,
        ))),
        "lookahead": tuple(enumerate((
            1, 1, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5,
            6, 6, 7, 7, 7, 7, 8, 8, 8, 7, 6, 6, 6, 5,
            5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1,
        ))),
    },
    "electrical": {
        "unit": "packages",
        "baseline": tuple(enumerate((
            1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2,
            2, 2, 2, 2, 2, 2, 3, 2, 2, 2, 2,
            2, 2, 1, 1, 1, 1, 1, 1, 1, 1,
        ))),
        "lookahead": tuple(enumerate((
            1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2,
            2, 2, 2, 2, 2, 3, 2, 2, 2, 2, 1, 2,
            1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1,
        ))),
    },
    "structural": {
        "unit": "packages",
        "baseline": tuple(enumerate((
            0, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            1, 1, 1, 2, 2, 1, 2, 1, 1, 1,
            1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1,
        ))),
        "lookahead": tuple(enumerate((
            1, 1, 1, 1, 1, 1, 2, 2,
            2, 2, 2, 2, 2, 2, 2, 1,
            1, 1, 1, 1, 1, 1, 1,
        ))),
    },
}


def _with_mode(payload: dict, mode: str, *, sample: bool = False) -> dict:
    result = deepcopy(payload)
    result.setdefault("source", {}).update({
        "mode": mode, "mode_label": mode.title(),
        "data_kind": "sample" if sample else "real", "is_sample": sample,
    })
    return result


def _electrical_fabrication_unavailable() -> dict:
    """The current DATAFY importer has no electrical fabrication discipline.

    Electrical drawings/material rows do not establish a dated fabrication
    scope. Do not borrow the structural schedule or fabricate a zero curve.
    """
    error = "No electrical fabrication schedule is available in DATAFY."
    payload = _empty_payload(error)
    payload["source"] = {
        "discipline": "electrical", "discipline_label": "Electrical",
        "title": "Electrical fabrication rundown", "unit": "packages", "unit_label": "packages",
        "source_label": "DATAFY · electrical fabrication schedule unavailable",
        "baseline_label": "Imported plan", "lookahead_label": "Lookahead", "has_lookahead": False,
        "workbook": "", "snapshot_date": "", "snapshot_label": "—",
        "notice": error,
    }
    payload["kpis"].update(scope_total=None, finish_variance_days=None)
    return payload


def installation_rundown_sample(discipline: str) -> dict:
    """Return a clearly labelled, deterministic example for one discipline."""
    if discipline not in _INSTALLATION_SAMPLES:
        raise ValueError("Unsupported installation rundown discipline")
    fixture = _INSTALLATION_SAMPLES[discipline]
    label = _DISCIPLINE_LABELS[discipline]
    scope_total = sum(quantity for _offset, quantity in fixture["baseline"])
    last_offset = max(offset for series in ("baseline", "lookahead") for offset, _qty in fixture[series])
    charts = {
        "dates": [(_INSTALLATION_SAMPLE_START + timedelta(days=offset)).isoformat()
                  for offset in range(last_offset + 2)],
    }
    for series in ("baseline", "lookahead"):
        releases = dict(fixture[series])
        final_release = max(releases)
        remaining = scope_total
        daily, rundown = [], []
        for offset in range(last_offset + 2):
            if offset > final_release + 1:
                daily.append(None)
                rundown.append(None)
                continue
            daily.append(releases.get(offset, 0))
            rundown.append(remaining)
            remaining -= releases.get(offset, 0)
        charts[f"{series}_total"] = daily
        charts[f"{series}_rundown"] = rundown
    source = {
        "discipline": discipline, "discipline_label": label,
        "title": f"{label} installation rundown", "unit": fixture["unit"], "unit_label": fixture["unit"],
        "source_label": "Sample data", "workbook": "", "sample_version": 2,
        "snapshot_date": _INSTALLATION_SAMPLE_AS_OF.isoformat(),
        "as_of_date": _INSTALLATION_SAMPLE_AS_OF.isoformat(),
        "baseline_label": "Sample baseline", "lookahead_label": "Sample lookahead", "has_lookahead": True,
        "notice": "Sample data for the installation view. These figures are simulated and do not represent reported offshore progress.",
        "scope_rule": f"Simulated {fixture['unit']} for the {label.lower()} installation example.",
        "date_rule": "Fixed sample installation dates; no operational dates are used.",
        "balance_rule": "Remaining scope is measured at the start of each day. A scheduled completion is deducted from the following day's balance.",
    }
    # Reuse the normal parser to enforce equal scopes, complete series,
    # start-of-day balances and finish-date KPI consistency in the examples.
    payload = fabrication_rundown(snapshot={"schema": 1, "source": source, **charts})
    payload["kpis"].update(scheduled_scope=scope_total, unscheduled_scope=0)
    return _with_mode(payload, "installation", sample=True)


def rundown_modes_safe(piping_payload: dict) -> dict[str, dict]:
    """Build both mode choices without changing the legacy discipline API.

    Fabrication preserves the accepted Piping ROS and live Structural plan.
    An unavailable live source remains unavailable; installation examples
    are separate and remain labelled Sample data even during source failures.
    """
    existing = rundown_disciplines_safe(piping_payload)
    fabrication = {
        "piping": _with_mode(existing["piping"], "fabrication"),
        "electrical": _with_mode(_electrical_fabrication_unavailable(), "fabrication"),
        "structural": _with_mode(existing["structural"], "fabrication"),
    }
    return {
        "fabrication": {"label": "Fabrication", "disciplines": fabrication},
        "installation": {
            "label": "Installation",
            "disciplines": {key: installation_rundown_sample(key) for key in _DISCIPLINE_LABELS},
        },
    }

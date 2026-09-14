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
from .rundown_source import _empty_payload

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

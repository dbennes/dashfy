"""AVEON fabrication dates for the existing skyline's exact line/spool scope.

The AVEON WBS spool counts differ from the ROS scope. Consequently a line's
original quantity is placed at its full fabrication finish, including painting;
it is never apportioned among unmatched P6 spool names. Weekly percentages and
planned dates do not constitute dated actual completion.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
import json
import logging
import re
from typing import Any

from django.utils import timezone

from . import fabrication_source as fabrication
from . import real_sources
from .skyline_material_source import line_identity
from .skyline_source import _empty_payload, _week_ending_friday

logger = logging.getLogger(__name__)

_PACKAGES_SQL = """
select p.id, p.code, p.name, p.document_id, p.drawing_number, p.p6_ref,
       p.plan_finish, p.actual_finish, p.stages, p.latest_import_id,
       d.piping_line_number as line, d.project_id,
       d.drawing_number as document_drawing_number,
       not exists(select 1 from core_document other_d
                   where other_d.id <> d.id and other_d.project_id = d.project_id
                     and upper(trim(other_d.drawing_number)) = upper(trim(d.drawing_number))) as drawing_identity_unique,
       i.original_filename as source_workbook, i.imported_at
  from fabrication_fabricationpackage p
  left join core_document d on d.id = p.document_id
  left join fabrication_p6import i on i.id = p.latest_import_id
 where p.is_active = true and p.discipline = 'piping'
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


def _scope(ros_payload: dict) -> dict[str, int]:
    """Copy quantities only: ROS dates and performed flags are not AVEON data."""
    buckets = ros_payload.get("charts", {}).get("dates", [])
    scenario = "forecast" if any(bucket.get("forecast") for bucket in buckets) else "lookahead"
    totals: dict[str, int] = defaultdict(int)
    for bucket in buckets:
        for segment in bucket.get(scenario, []):
            line = str(segment.get("line") or "").strip()
            quantity = segment.get("spools")
            if line and isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0:
                totals[line] += quantity
    return dict(totals)


def _package_name_line(value: Any) -> str:
    # Some source names have quotes inside the schedule suffix (e.g.
    # 12"-PM-043107-"1800"-IFJ). Read the explicit physical line token only.
    text = str(value or "").strip().upper().replace("″", '"')
    match = re.match(r'^(\d+(?:[.-]\d+/\d+|/\d+)?)"-([A-Z]{2})-(\d{6})(?=-|_|$)', text)
    return line_identity(f'{match[1]}"-{match[2]}-{match[3]}') if match else ""


def _fabrication_finish(package: dict) -> date | None:
    stages = fabrication._as_dict(package.get("stages"))
    scheduled = [stages[key] for key in fabrication.STAGE_KEYS
                 if isinstance(stages.get(key), dict)
                 and ("plan_finish" in stages[key] or stages[key].get("acts"))]
    finishes = [_date(stage.get("plan_finish")) for stage in scheduled]
    return max(finishes) if finishes and all(finishes) else None


def _progress(package: dict) -> dict:
    stages = fabrication._as_dict(package.get("stages"))
    weekly = fabrication._weekly_overall_value(stages)
    marker = stages.get(fabrication.WEEKLY_PROGRESS_META_KEY, {})
    report_date = str(marker.get("report_date") or "") if weekly is not None else ""
    imported = _date(package.get("imported_at"))
    return {
        "package_id": package["id"], "package_code": package.get("code") or "",
        "pct": float(fabrication.overall_value(stages)),
        "source": "EPC1 ISO weekly fabrication report" if weekly is not None else package.get("source_workbook") or "AVEON P6 stages",
        "as_of_date": report_date or (imported.isoformat() if imported else ""),
    }


def _base_payload(ros_payload: dict, scope: dict[str, int], as_of: date) -> dict:
    payload = _empty_payload()
    payload["source"] = {
        "mode": "aveon", "source_label": "AVEON fabrication schedule",
        "workbook": "", "snapshot_date": "", "snapshot_label": "",
        "as_of_date": as_of.isoformat(), "as_of_label": as_of.strftime("%d %b %y"),
        "forecast_label": "Planned fabrication finish",
        "lookahead_label": "Confirmed actual fabrication finish",
        "date_rule": "Latest planned finish across fabrication stages, including painting. Actual dates require explicit AVEON actual finish evidence.",
        "scope_rule": "Same line and spool scope as ROS; quantities are not inferred from AVEON WBS spool names.",
        "actual_date_note": "No actual fabrication finish dates are confirmed in the imported AVEON schedule.",
        "material_readiness_label": ros_payload.get("source", {}).get("material_readiness_label", ""),
        "material_readiness_available": ros_payload.get("source", {}).get("material_readiness_available", False),
    }
    payload["kpis"].update(
        line_count=len(scope), scope_spools=sum(scope.values()),
        scheduled_line_count=0, scheduled_spools=0,
        unmapped_line_count=0, unmapped_spools=0,
        confirmed_actual_line_count=0, confirmed_actual_spools=0,
        remaining_line_count=len(scope), remaining_spools=sum(scope.values()),
        upcoming_line_count=len(scope), upcoming_spools=sum(scope.values()),
    )
    payload["charts"]["unmapped"] = []
    payload["charts"]["material_readiness"] = deepcopy(ros_payload.get("charts", {}).get("material_readiness", {}))
    return payload


def build_aveon_skyline(ros_payload: dict, packages: list[dict]) -> dict:
    """Build AVEON bands without reading or borrowing any ROS schedule dates."""
    scope = _scope(ros_payload)
    as_of = _date(ros_payload.get("source", {}).get("as_of_date")) or timezone.localdate()
    payload = _base_payload(ros_payload, scope, as_of)
    by_line: dict[str, list[dict]] = defaultdict(list)
    conflicts: set[str] = set()
    for package in packages:
        package = dict(package)
        document_line = line_identity(package.get("line"))
        name_line = _package_name_line(package.get("name"))
        if document_line and name_line and document_line != name_line:
            drawing = str(package.get("drawing_number") or "").strip().upper()
            linked_drawing = str(package.get("document_drawing_number") or "").strip().upper()
            if package.get("document_id") and drawing and drawing == linked_drawing and package.get("drawing_identity_unique") is True:
                package["line_mapping_note"] = (
                    f"Exact linked drawing {drawing} identifies {document_line}; "
                    f"the AVEON WBS name uses {name_line}."
                )
            else:
                conflicts.update((document_line, name_line))
                continue
        identity = document_line or name_line
        if identity:
            by_line[identity].append(package)
    buckets: dict[date, dict] = {}
    workbooks: set[str] = set()
    import_dates: list[date] = []
    imports: set[int] = set()
    planned_dates: list[date] = []
    actual_dates: list[date] = []
    status_lines: dict[str, set[str]] = defaultdict(set)

    def bucket_for(value: date) -> dict:
        week = _week_ending_friday(value)
        return buckets.setdefault(week, {
            "date": week.isoformat(), "label": week.strftime("%d %b %y"),
            "forecast": [], "lookahead": [], "forecast_total": 0,
            "lookahead_total": 0, "performed_total": 0, "remaining_total": 0,
        })

    for line, spools in scope.items():
        identity = line_identity(line)
        linked = by_line.get(identity, [])
        reason = ""
        if identity in conflicts:
            reason = "AVEON package and DATAFY drawing disagree on the line identity."
        elif not linked:
            reason = "No matching active AVEON fabrication package."
        elif len({p.get("project_id") for p in linked if p.get("project_id") is not None}) > 1:
            reason = "Line matches multiple DATAFY projects."
        elif any("AVEON" not in str(p.get("source_workbook") or "").upper() for p in linked):
            reason = "The package has no attributable AVEON schedule import."
        elif any(_fabrication_finish(package) is None for package in linked):
            reason = "AVEON fabrication stages have no complete planned finish date."
        if reason:
            payload["charts"]["unmapped"].append({"line": line, "spools": spools, "reason": reason})
            continue
        planned = max(_fabrication_finish(package) for package in linked)
        confirmed = [_date(package.get("actual_finish")) for package in linked]
        actual = max(confirmed) if all(value is not None and value <= as_of for value in confirmed) else None
        progress = [_progress(package) for package in linked]
        progress_single = progress[0] if len(progress) == 1 else {}
        evidence = {
            "line": line, "spools": spools, "line_spools": spools,
            "line_performed_spools": spools if actual else 0,
            "line_remaining_spools": 0 if actual else spools,
            "progress_pct": 100.0 if actual else 0.0,
            "has_upcoming": actual is None,
            "date_source": "AVEON fabrication stages (including painting)",
            "source_workbook": ", ".join(sorted({p["source_workbook"] for p in linked})),
            "package_ids": [p["id"] for p in linked],
            "p6_refs": [p.get("p6_ref") or "" for p in linked],
            "line_mapping_note": " ".join(p["line_mapping_note"] for p in linked if p.get("line_mapping_note")),
            "fabrication_progress_pct": progress_single.get("pct"),
            "progress_source": progress_single.get("source", "Per-package fabrication reports"),
            "progress_as_of_date": progress_single.get("as_of_date", ""),
            "fabrication_progress": progress,
            "actual_date_confirmed": actual is not None,
            "planned_finish": planned.isoformat(),
            "actual_finish": actual.isoformat() if actual else "",
        }
        evidence["schedule_note"] = evidence["line_mapping_note"]
        forecast = dict(evidence, date=planned.isoformat(), dates=[planned.isoformat()],
                        date_kind="planned", status="upcoming", performed_spools=0, remaining_spools=spools)
        planned_bucket = bucket_for(planned)
        planned_bucket["forecast"].append(forecast)
        planned_bucket["forecast_total"] += spools
        planned_dates.append(planned)
        payload["kpis"]["scheduled_line_count"] += 1
        payload["kpis"]["scheduled_spools"] += spools
        if actual:
            status = "on_time" if actual <= planned else "late"
            actual_bucket = bucket_for(actual)
            actual_bucket["lookahead"].append(dict(
                evidence, date=actual.isoformat(), dates=[actual.isoformat()], date_kind="actual",
                date_source="AVEON explicit actual fabrication finish", status=status,
                performed_spools=spools, remaining_spools=0,
            ))
            actual_bucket["lookahead_total"] += spools
            actual_bucket["performed_total"] += spools
            payload["charts"]["status_totals"][status] += spools
            status_lines[status].add(line)
            payload["kpis"]["confirmed_actual_line_count"] += 1
            payload["kpis"]["confirmed_actual_spools"] += spools
            actual_dates.append(actual)
        for package in linked:
            workbooks.add(package["source_workbook"])
            imported = _date(package.get("imported_at"))
            if imported:
                import_dates.append(imported)
            if package.get("latest_import_id"):
                imports.add(package["latest_import_id"])
    kpis = payload["kpis"]
    kpis["entry_count"] = kpis["scheduled_line_count"]
    kpis["unmapped_line_count"] = len(payload["charts"]["unmapped"])
    kpis["unmapped_spools"] = sum(row["spools"] for row in payload["charts"]["unmapped"])
    kpis["performed_line_count"] = kpis["confirmed_actual_line_count"]
    kpis["performed_spools"] = kpis["confirmed_actual_spools"]
    kpis["remaining_line_count"] = kpis["line_count"] - kpis["performed_line_count"]
    kpis["remaining_spools"] = kpis["scope_spools"] - kpis["performed_spools"]
    kpis["upcoming_line_count"] = kpis["remaining_line_count"]
    kpis["upcoming_spools"] = kpis["remaining_spools"]
    for status in ("on_time", "late", "partial"):
        kpis[f"{status}_line_count"] = len(status_lines[status])
        kpis[f"{status}_spools"] = payload["charts"]["status_totals"][status]
        payload["charts"]["status_line_counts"][status] = len(status_lines[status])
    kpis["baseline_last_release_label"] = max(planned_dates).strftime("%d %b %y") if planned_dates else "—"
    kpis["lookahead_last_release_label"] = max(actual_dates).strftime("%d %b %y") if actual_dates else "—"
    payload["charts"]["dates"] = [buckets[week] for week in sorted(buckets)]
    for bucket in payload["charts"]["dates"]:
        for band in ("forecast", "lookahead"):
            bucket[band].sort(key=lambda row: (-row["spools"], row["line"]))
    payload["source"].update(workbook=", ".join(sorted(workbooks)), import_ids=sorted(imports))
    if import_dates:
        imported = max(import_dates)
        payload["source"].update(snapshot_date=imported.isoformat(), snapshot_label=imported.strftime("%d %b %y"))
    if actual_dates:
        payload["source"]["actual_date_note"] = "Only explicit, nonfuture AVEON actual finish dates appear in the actual band."
    payload["available"] = bool(planned_dates)
    payload["error"] = "" if planned_dates else "No AVEON fabrication dates are available for this scope."
    payload["charts_json"] = json.dumps(payload["charts"], separators=(",", ":"))
    return payload


def aveon_skyline(ros_payload: dict) -> dict:
    with real_sources._datafy_conn() as conn:
        packages = real_sources._rows(conn.cursor(), _PACKAGES_SQL)
    return build_aveon_skyline(ros_payload, packages)


def aveon_skyline_safe(ros_payload: dict) -> dict:
    try:
        return aveon_skyline(ros_payload)
    except Exception:
        logger.exception("AVEON skyline source unavailable")
        payload = build_aveon_skyline(ros_payload, [])
        payload["error"] = "The AVEON fabrication source could not be refreshed."
        return payload

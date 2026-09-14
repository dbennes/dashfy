"""AVEON fabrication dates for the existing skyline's exact line/spool scope.

The AVEON WBS spool counts differ from the ROS scope. Consequently a line's
original quantity is placed at its full fabrication finish, including painting;
it is never apportioned among unmatched P6 spool names. The upper band uses
planned finishes; the lower band shows completed lines at confirmed actual
finishes. Reported completion without an actual date remains separate evidence.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
import logging
import re
from typing import Any

from django.utils import timezone

from . import fabrication_source as fabrication
from . import real_sources
from .skyline_material_source import line_identity
from .skyline_source import _empty_payload, _week_ending_friday
from .skyline_progress_source import confirmed_actual_finish, is_complete, package_progress

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

_PROGRESS_SQL = """
select e.id, e.package_id, e.progress_date, e.stages, e.overall_after
  from fabrication_fabricationprogressentry e
  join fabrication_fabricationpackage p on p.id = e.package_id
 where p.is_active = true and p.discipline = 'piping' and e.progress_date <= ?
 order by e.progress_date, e.id
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


def _base_payload(ros_payload: dict, scope: dict[str, int], as_of: date) -> dict:
    payload = _empty_payload()
    payload["source"] = {
        "mode": "aveon", "source_label": "AVEON fabrication schedule",
        "workbook": "", "snapshot_date": "", "snapshot_label": "",
        "as_of_date": as_of.isoformat(), "as_of_label": as_of.strftime("%d %b %y"),
        "forecast_label": "Planned fabrication finish",
        "lookahead_label": "Actual fabrication finish",
        "date_rule": "The upper band uses planned fabrication finish, including painting. The lower band shows only completed lines at their confirmed actual finish, green on or before plan and red after plan. Report dates never substitute for actual finish dates.",
        "scope_rule": "Same line and spool scope as ROS; quantities are not inferred from AVEON WBS spool names.",
        "actual_date_note": "Report dates show when fabrication progress was recorded. They are not inferred actual finish dates. Spool quantities are line scope, not percentage-based completed quantities.",
        "material_readiness_label": ros_payload.get("source", {}).get("material_readiness_label", ""),
        "material_readiness_available": ros_payload.get("source", {}).get("material_readiness_available", False),
    }
    payload["kpis"].update(
        line_count=len(scope), scope_spools=sum(scope.values()),
        scheduled_line_count=0, scheduled_spools=0,
        unmapped_line_count=0, unmapped_spools=0,
        confirmed_actual_line_count=0, confirmed_actual_spools=0,
        undated_completed_lines=0, undated_completed_spools=0,
        reported_completed_line_count=0, reported_completed_spools=0,
        reported_line_count=0, reported_spools=0, progress_report_date="",
        completed_line_count=0, completed_spools=0,
        remaining_line_count=len(scope), remaining_spools=sum(scope.values()),
        upcoming_line_count=len(scope), upcoming_spools=sum(scope.values()),
    )
    payload["charts"]["unmapped"] = []
    payload["charts"]["undated_completions"] = []
    payload["charts"]["status_totals"]["completed"] = 0
    payload["charts"]["status_line_counts"]["completed"] = 0
    payload["charts"]["material_readiness"] = deepcopy(ros_payload.get("charts", {}).get("material_readiness", {}))
    return payload


def build_aveon_skyline(ros_payload: dict, packages: list[dict], progress_entries: list[dict] | None = None) -> dict:
    """Build AVEON bands without reading or borrowing any ROS schedule dates."""
    scope = _scope(ros_payload)
    as_of = _date(ros_payload.get("source", {}).get("as_of_date")) or timezone.localdate()
    payload = _base_payload(ros_payload, scope, as_of)
    history_by_package = defaultdict(list)
    for entry in progress_entries or []:
        history_by_package[entry["package_id"]].append(entry)
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
    report_dates: list[str] = []
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
        if reason:
            payload["charts"]["unmapped"].append({"line": line, "spools": spools, "reason": reason})
            continue
        finishes = [_fabrication_finish(package) for package in linked]
        planned = max(finishes) if all(finishes) else None
        if planned is None:
            payload["charts"]["unmapped"].append({
                "line": line, "spools": spools,
                "reason": "Fabrication stages have no complete planned finish date; the line cannot be positioned in the planned band.",
            })
        confirmed = [confirmed_actual_finish(package, as_of) for package in linked]
        actual = max(confirmed) if all(value is not None for value in confirmed) else None
        progress = [package_progress(package, history_by_package[package["id"]], as_of) for package in linked]
        source_actual = actual
        actual_superseded = actual is not None and any(
            any(_date(observation["date"]) >= finish and not is_complete(observation["pct_exact"])
                for observation in item["history"])
            for finish, item in zip(confirmed, progress)
        )
        if actual_superseded:
            actual = None
        progress_single = progress[0] if len(progress) == 1 else {}
        known_progress = all(item["pct_exact"] is not None for item in progress)
        reported_pct = (sum(Decimal(item["pct_exact"]) for item in progress) / len(progress)) if known_progress else None
        report_date = max((item["as_of_date"] for item in progress if item["as_of_date"]), default="")
        reported_complete = known_progress and all(is_complete(item["pct_exact"]) for item in progress)
        complete = actual is not None
        progress_pct = 100.0 if complete or reported_complete else float(reported_pct) if reported_pct is not None else None
        reported_completion = max((item["completed_date"] for item in progress), default="") if reported_complete else ""
        if actual:
            status = ("on_time" if actual <= planned else "late") if planned else "completed"
            progress_date_kind = "actual"
        elif reported_complete:
            status, progress_date_kind = "undated", "reported_complete"
        elif reported_pct is not None and reported_pct > 0:
            status, progress_date_kind = "partial", "progress"
        else:
            status = "upcoming"
            progress_date_kind = "progress" if report_date else "planned"
        progress_source = (progress_single.get("source") or "DATAFY fabrication progress unavailable") if len(progress) == 1 else "DATAFY fabrication packages (arithmetic average)"
        evidence = {
            "line": line, "spools": spools, "line_spools": spools,
            "line_performed_spools": spools if complete else 0,
            "line_remaining_spools": 0 if complete else spools,
            "progress_pct": progress_pct,
            "progress_basis": "fabrication_report",
            "has_upcoming": not complete,
            "date_source": "AVEON fabrication stages (including painting)",
            "source_workbook": ", ".join(sorted({p["source_workbook"] for p in linked})),
            "package_ids": [p["id"] for p in linked],
            "p6_refs": [p.get("p6_ref") or "" for p in linked],
            "line_mapping_note": " ".join(p["line_mapping_note"] for p in linked if p.get("line_mapping_note")),
            "fabrication_progress_pct": float(reported_pct) if reported_pct is not None else None,
            "progress_source": progress_source,
            "progress_source_filename": progress_single.get("source_filename", ""),
            "progress_as_of_date": report_date,
            "progress_date_kind": progress_date_kind,
            "fabrication_progress": progress,
            "progress_history": [dict(observation, package_id=item["package_id"], package_code=item["package_code"])
                                 for item in progress for observation in item["history"]],
            "actual_date_confirmed": actual is not None,
            "planned_finish": planned.isoformat() if planned else "",
            "actual_finish": actual.isoformat() if actual else "",
            "source_actual_finish": source_actual.isoformat() if source_actual else "",
            "progress_conflict_note": ("A later fabrication report below 100% supersedes the earlier actual finish dated " + source_actual.isoformat() + ".") if actual_superseded else "",
            "reported_completion_date": reported_completion,
            "progress_note": "Percentages describe fabrication progress. Spool counts describe the line scope; partial percentages do not count finished spools."
                + (" Multiple packages use the same arithmetic-average convention as the Fabrication summary; all packages must be complete to finish the line." if len(progress) > 1 else ""),
        }
        evidence["schedule_note"] = evidence["line_mapping_note"]
        if planned is None:
            payload["charts"]["unmapped"][-1].update({
                "fabrication_progress_pct": evidence["fabrication_progress_pct"],
                "progress_as_of_date": report_date, "status": status,
                "actual_finish": evidence["actual_finish"],
                "reported_completion_date": evidence["reported_completion_date"],
                "progress_source": progress_source,
            })
        if planned:
            forecast = dict(evidence, date=planned.isoformat(), dates=[planned.isoformat()],
                            date_kind="planned", status="upcoming", performed_spools=0, remaining_spools=spools)
            planned_bucket = bucket_for(planned)
            planned_bucket["forecast"].append(forecast)
            planned_bucket["forecast_total"] += spools
            planned_dates.append(planned)
            payload["kpis"]["scheduled_line_count"] += 1
            payload["kpis"]["scheduled_spools"] += spools
        if actual:
            actual_bucket = bucket_for(actual)
            actual_bucket["lookahead"].append(dict(
                evidence, date=actual.isoformat(), dates=[actual.isoformat()], date_kind="actual",
                date_source="DATAFY confirmed actual fabrication finish (including painting)",
                status=status, performed_spools=spools, remaining_spools=0,
            ))
            actual_bucket["lookahead_total"] += spools
            actual_bucket["performed_total"] += spools
            actual_dates.append(actual)
            payload["charts"]["status_totals"][status] += spools
            status_lines[status].add(line)
        elif reported_complete:
            payload["charts"]["undated_completions"].append(dict(
                evidence, status="undated",
                reason="Reported 100% complete; a confirmed actual finish date is missing.",
            ))
            payload["kpis"]["undated_completed_lines"] += 1
            payload["kpis"]["undated_completed_spools"] += spools
        if reported_complete:
            payload["kpis"]["reported_completed_line_count"] += 1
            payload["kpis"]["reported_completed_spools"] += spools
        if known_progress:
            payload["kpis"]["reported_line_count"] += 1
            payload["kpis"]["reported_spools"] += spools
            if report_date:
                report_dates.append(report_date)
        if actual:
            payload["kpis"]["confirmed_actual_line_count"] += 1
            payload["kpis"]["confirmed_actual_spools"] += spools
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
    kpis["progress_report_date"] = max(report_dates, default="")
    kpis["performed_line_count"] = sum(len(status_lines[status]) for status in ("on_time", "late", "completed"))
    kpis["performed_spools"] = sum(payload["charts"]["status_totals"][status] for status in ("on_time", "late", "completed"))
    kpis["remaining_line_count"] = kpis["line_count"] - kpis["performed_line_count"]
    kpis["remaining_spools"] = kpis["scope_spools"] - kpis["performed_spools"]
    for status in ("on_time", "late", "partial", "upcoming", "completed"):
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
    payload["source"]["progress_report_date"] = kpis["progress_report_date"]
    payload["available"] = bool(planned_dates or actual_dates)
    payload["error"] = "" if payload["available"] else "No planned or confirmed actual fabrication finish dates are available for this scope."
    payload["charts_json"] = json.dumps(payload["charts"], separators=(",", ":"))
    return payload


def aveon_skyline(ros_payload: dict) -> dict:
    as_of = _date(ros_payload.get("source", {}).get("as_of_date")) or timezone.localdate()
    with real_sources._datafy_conn() as conn:
        packages = real_sources._rows(conn.cursor(), _PACKAGES_SQL)
        progress_entries = real_sources._rows(conn.cursor(), _PROGRESS_SQL, (as_of,))
    return build_aveon_skyline(ros_payload, packages, progress_entries)


def aveon_skyline_safe(ros_payload: dict) -> dict:
    try:
        return aveon_skyline(ros_payload)
    except Exception:
        logger.exception("AVEON skyline source unavailable")
        payload = build_aveon_skyline(ros_payload, [])
        payload["error"] = "The AVEON fabrication source could not be refreshed."
        return payload

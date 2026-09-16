"""Simulated Piping installation dates over the real ROS line/spool scope."""

from datetime import date, timedelta
import json

from .rundown_discipline_source import installation_rundown_sample
from .skyline_aveon_source import _scope
from .skyline_source import _empty_payload, _week_ending_friday


_STATUSES = ("on_time", "late", "partial", "upcoming", "completed")
_SAMPLE_DAY_SCALE = 4


def _line_completion_dates(charts: dict, series: str, lines: list[tuple[str, int]]) -> dict[str, date]:
    """Scale the example's daily profile to scope, completing whole real lines."""
    result = {}
    scope_spools = sum(spools for _, spools in lines)
    sample_quantities = [int(value or 0) for value in charts[f"{series}_total"]]
    sample_total = sum(sample_quantities)
    cumulative_sample = 0
    allocated_spools = 0
    next_line = 0
    for day, quantity in zip(charts["dates"], sample_quantities):
        cumulative_sample += quantity
        capacity = cumulative_sample * scope_spools // sample_total
        while next_line < len(lines):
            line, spools = lines[next_line]
            if allocated_spools + spools > capacity:
                break
            result[line] = date.fromisoformat(day)
            allocated_spools += spools
            next_line += 1
    if next_line != len(lines):
        raise ValueError("Installation sample profile must cover the entire line scope")
    return result


def installation_skyline_sample(ros_payload: dict) -> dict:
    """Preserve ROS identifiers/quantities; simulate only dates and progress.

    The real scope is supplied by the dashboard's existing ROS load, using the
    same scope extraction as Fabrication. The sample daily profile is scaled to
    that scope; it does not change the Installation Rundown. No source reads or
    writes occur here, and missing scope never falls back to invented lines.
    """
    rundown = installation_rundown_sample("piping")
    sample_source = rundown["source"]
    scope_source = ros_payload.get("source", {})
    line_scope = _scope(ros_payload)
    planned_order = sorted(line_scope.items())
    scope = sum(line_scope.values())
    as_of = date.fromisoformat(sample_source["as_of_date"])
    planned_dates = _line_completion_dates(rundown["charts"], "baseline", planned_order)
    # A different execution sequence illustrates both early and late lines.
    completion_order = []
    for start in range(0, len(planned_order), 3):
        group = planned_order[start:start + 3]
        completion_order.extend(group[-1:] + group[:-1])
    completion_by_line = _line_completion_dates(rundown["charts"], "lookahead", completion_order)

    # Spread this Skyline over a longer horizon so weekly columns stay compact.
    # Anchoring both series on the cutoff preserves completion and delay status.
    planned_dates = {
        line: as_of + timedelta(days=(day - as_of).days * _SAMPLE_DAY_SCALE)
        for line, day in planned_dates.items()
    }
    completion_by_line = {
        line: as_of + timedelta(days=(day - as_of).days * _SAMPLE_DAY_SCALE)
        for line, day in completion_by_line.items()
    }

    payload = _empty_payload()
    payload["available"] = bool(line_scope)
    payload["error"] = "" if line_scope else "Installation sample unavailable: no ROS line and spool scope is available."
    payload["source"] = {
        "mode": "installation", "mode_label": "Installation",
        "discipline": "piping", "discipline_label": "Piping",
        "title": "Piping installation skyline", "unit": "spools", "unit_label": "spools",
        "source_label": "Sample data", "is_sample": True, "data_kind": "sample",
        "sample_version": 4, "workbook": "", "import_ids": [],
        "scope_kind": "real", "scope_source": "ROS",
        "scope_workbook": scope_source.get("workbook", ""),
        "scope_snapshot_date": scope_source.get("snapshot_date", ""),
        "scope_snapshot_label": scope_source.get("snapshot_label", ""),
        "snapshot_date": sample_source["snapshot_date"],
        "snapshot_label": date.fromisoformat(sample_source["snapshot_date"]).strftime("%d %b %y"),
        "as_of_date": as_of.isoformat(), "as_of_label": as_of.strftime("%d %b %y"),
        "forecast_label": "Planned installation finish", "lookahead_label": "Completed installation",
        "notice": "Real ROS lines and spool quantities. Only installation dates and progress are simulated.",
        "scope_rule": "Same line identifiers and per-line spool quantities as Wooden Box / ROS. Completed totals include only whole lines completed in the simulation.",
        "date_rule": "Simulated installation dates use a fixed profile scaled to the real ROS spool scope and spread over a longer horizon for compact weekly columns. Planned finishes appear above; only whole lines completed by the sample reporting date appear below.",
        "actual_date_note": "Completion dates are simulated installation dates, not operational records.",
        "material_readiness_label": "Material readiness is not included in this sample.",
        "material_readiness_available": False,
        "progress_report_date": as_of.isoformat(),
    }
    kpis = payload["kpis"]
    kpis.update({
        "line_count": len(planned_dates), "entry_count": len(planned_dates), "scope_spools": scope,
        "scheduled_line_count": len(planned_dates), "scheduled_spools": scope,
        "unmapped_line_count": 0, "unmapped_spools": 0,
        "confirmed_actual_line_count": 0, "confirmed_actual_spools": 0,
        "estimated_completion_line_count": 0, "estimated_completion_spools": 0,
        "undated_completed_lines": 0, "undated_completed_spools": 0,
        "reported_line_count": 0, "reported_spools": 0,
        "reported_completed_line_count": 0, "reported_completed_spools": 0,
        "progress_report_date": as_of.isoformat(),
        "last_release_variance_days": None,
    })
    charts = payload["charts"]
    charts.update({
        "unmapped": [], "undated_completions": [], "estimated_completions": [],
        "material_readiness": {},
        "status_totals": {status: 0 for status in _STATUSES},
        "status_line_counts": {status: 0 for status in _STATUSES},
    })
    buckets = {}

    def bucket_for(day: date) -> dict:
        week = _week_ending_friday(day)
        return buckets.setdefault(week, {
            "date": week.isoformat(), "label": week.strftime("%d %b %y"),
            "forecast": [], "lookahead": [], "forecast_total": 0, "lookahead_total": 0,
            "performed_total": 0, "remaining_total": 0,
        })

    completed_dates = []
    for line, spools in planned_order:
        planned = planned_dates[line]
        completion = completion_by_line[line]
        complete = completion <= as_of
        evidence = {
            "line": line, "is_sample": True, "scope_kind": "real", "scope_source": "ROS",
            "source_label": "Sample data", "package_ids": [], "documents": [], "p6_refs": [],
            "spools": spools, "line_spools": spools,
            "line_performed_spools": spools if complete else 0,
            "line_remaining_spools": 0 if complete else spools,
            "progress_pct": 100 if complete else 0, "progress_basis": "installation_sample",
            "progress_source": "Sample data", "progress_as_of_date": as_of.isoformat(),
            "has_upcoming": not complete, "planned_finish": planned.isoformat(),
            "actual_finish": "",
            "actual_date_confirmed": False,
            "completion_date": completion.isoformat() if complete else "",
            "completion_date_kind": "sample" if complete else "",
            "completion_estimate": {}, "reported_completion_date": "",
            "progress_note": "Simulated installation progress. Spools count as completed only when the whole line is complete.",
        }
        forecast = dict(
            evidence, date=planned.isoformat(), dates=[planned.isoformat()], date_kind="planned",
            date_source="Sample planned installation finish", status="upcoming",
            performed_spools=0, remaining_spools=spools,
        )
        planned_bucket = bucket_for(planned)
        planned_bucket["forecast"].append(forecast)
        planned_bucket["forecast_total"] += spools
        if complete:
            status = "on_time" if completion <= planned else "late"
            completed = dict(
                evidence, date=completion.isoformat(), dates=[completion.isoformat()], date_kind="sample",
                date_source="Sample installation finish", status=status,
                performed_spools=spools, remaining_spools=0,
            )
            actual_bucket = bucket_for(completion)
            actual_bucket["lookahead"].append(completed)
            actual_bucket["lookahead_total"] += spools
            actual_bucket["performed_total"] += spools
            charts["status_totals"][status] += spools
            charts["status_line_counts"][status] += 1
            completed_dates.append(completion)

    kpis["performed_line_count"] = len(completed_dates)
    kpis["performed_spools"] = sum(charts["status_totals"].values())
    kpis["remaining_line_count"] = kpis["line_count"] - kpis["performed_line_count"]
    kpis["remaining_spools"] = scope - kpis["performed_spools"]
    for status in _STATUSES:
        kpis[f"{status}_line_count"] = charts["status_line_counts"][status]
        kpis[f"{status}_spools"] = charts["status_totals"][status]
    kpis["baseline_last_release_label"] = max(planned_dates.values()).strftime("%d %b %y") if planned_dates else "—"
    kpis["lookahead_last_release_label"] = max(completed_dates).strftime("%d %b %y") if completed_dates else "—"
    charts["dates"] = [buckets[week] for week in sorted(buckets)]
    for bucket in charts["dates"]:
        for band in ("forecast", "lookahead"):
            bucket[band].sort(key=lambda segment: segment["line"])
    payload["charts_json"] = json.dumps(charts, separators=(",", ":"))
    return payload

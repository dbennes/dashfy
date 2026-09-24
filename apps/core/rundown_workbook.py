"""Round-trip the daily tables behind every rundown discipline/mode."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from django.core import signing
from django.db import transaction, IntegrityError
from django.utils import timezone
from openpyxl import load_workbook
import xlsxwriter

from .models import RundownImport
from .rundown_xlsx import compact_workbook

DISCIPLINES = {"piping": "Piping", "electrical": "Electrical", "structural": "Structural"}
MODES = {"fabrication": "Fabrication", "installation": "Installation"}
SHEETS = {f"{mode}:{discipline}": f"{label} - {mode_label}"
          for mode, mode_label in MODES.items() for discipline, label in DISCIPLINES.items()}
HEADERS = ["Date", "Baseline daily", "Lookahead daily", "Actual daily", "Baseline remaining", "Lookahead remaining", "Actual remaining", "Progress %"]
SALT = "core.rundown-workbook.v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_modes():
    from . import ros_workbook, rundown_source, rundown_discipline_source
    schedule = ros_workbook.load_current_schedule()
    piping = rundown_source.fabrication_rundown(snapshot=schedule["rundown"])
    return rundown_discipline_source.rundown_modes_safe(piping)


def tables_from_modes(modes):
    tables = {}
    for key in SHEETS:
        mode, discipline = key.split(":")
        payload = modes[mode]["disciplines"][discipline]
        source, charts = payload["source"], payload["charts"]
        real = bool(payload["available"] and not source.get("is_sample"))
        rows = []
        if real:
            for index, day in enumerate(charts["dates"]):
                rows.append([day, *[(charts.get(series) or [None] * len(charts["dates"]))[index]
                                    for series in ("baseline_total", "lookahead_total", "actual_total")]])
        tables[key] = {"enabled": real, "scope": (payload["kpis"].get("scope_total") or 0) if real else 0,
                       "data_date": (source.get("snapshot_date") or source.get("as_of_date") or timezone.localdate().isoformat()) if real else "",
                       "unit": source.get("unit", "packages"), "rows": rows}
    return tables


def current_state():
    modes = source_modes()
    batch = RundownImport.objects.first()
    tables = tables_from_modes(modes)
    if batch:
        tables.update(deepcopy(batch.payload))
    return {"revision": str(batch.revision) if batch else "initial", "tables": tables,
            "fingerprint": digest(tables), "overrides": deepcopy(batch.payload) if batch else {}}


def export_workbook(current):
    output = BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    header = book.add_format({"bold": True, "bg_color": "#183D5D", "font_color": "white", "text_wrap": True})
    edit = book.add_format({"bg_color": "#FFF3CC", "num_format": "0"})
    day_format = book.add_format({"bg_color": "#FFF3CC", "num_format": "yyyy-mm-dd"})
    derived = book.add_format({"bg_color": "#EDF1F5", "num_format": "0"})
    percent = book.add_format({"bg_color": "#EDF1F5", "num_format": "0.0%"})
    info = book.add_worksheet("Instructions")
    info.set_column(0, 0, 110)
    notes = ["Rundown — export, update and import",
             "Each discipline has one Fabrication sheet and one Installation sheet. Yellow cells are editable.",
             "Rows are daily quantities feeding the rundown, not individual ISO/material records. Dates: YYYY-MM-DD. Quantities: non-negative whole units.",
             "Set Include on import to YES for sheets to update. NO leaves the current view unchanged. Set Scope and Data date.",
             "Edit columns A–D from row 10. Add/remove dates as needed; each date must be unique. Blank actual means not reported; 0 means zero completed that day.",
             "Actual daily is the quantity completed ON THAT DAY, not cumulative. Actual cannot be reported after Data date. Totals cannot exceed Scope.",
             "Grey columns are recalculated on import. Formulas in yellow cells use results saved by Excel: recalculate and save before uploading. Auxiliary columns after H are ignored.",
             "Baseline/lookahead balances are at the start of the day. Actual remaining and Progress % are at the end of the reported day.",
             "Sample Installation data is deliberately exported as empty templates. Fill with real data and choose YES to replace a sample view.",
             "Import previews changes before applying. Only the latest export can be applied; export again if another user or a source updated the data.",
             "Updates feed the Rundown card and are stored in DASHFY history. DATAFY package progress, Skyline and the 3D progress colours remain source-managed."]
    for index, note in enumerate(notes):
        info.write(index, 0, note, header if index == 0 else None)
        info.set_row(index, 30 if index else 24)
    for key, title in SHEETS.items():
        data = current["tables"][key]
        sheet = book.add_worksheet(title)
        sheet.set_column("A:A", 14, day_format)
        sheet.set_column("B:D", 19, edit)
        sheet.set_column("E:H", 21, derived)
        sheet.merge_range("A1:H1", title + " rundown", header)
        for row, label, value in [(1, "Scope", data["scope"]), (2, "Data date", data["data_date"]),
                                  (3, "Unit", data["unit"]), (4, "Include on import", "YES" if data["enabled"] else "NO")]:
            sheet.write(row, 0, label)
            if row == 2 and value:
                sheet.write_datetime(row, 1, date.fromisoformat(value), day_format)
            else:
                sheet.write(row, 1, value, derived if row == 3 else edit)
        sheet.data_validation("B5", {"validate": "list", "source": ["YES", "NO"]})
        sheet.merge_range("A7:H7", "Edit yellow cells. Daily completed quantities go in Actual daily; balances and progress are recalculated.")
        sheet.write_row(8, 0, HEADERS, header)
        sheet.set_row(8, 30)
        sheet.freeze_panes(9, 1)
        totals = [0, 0, 0]
        for offset, row in enumerate(data["rows"] or [[None, None, None, None]]):
            excel_row = offset + 10
            if row[0]:
                sheet.write_datetime(excel_row-1, 0, date.fromisoformat(row[0]), day_format)
            for column in (1, 2, 3):
                sheet.write(excel_row-1, column, row[column], edit)
            for column, letter in [(4, "B"), (5, "C")]:
                before = f'SUM({letter}$10:{letter}{excel_row-1})' if offset else '0'
                formula = f'=IF({letter}{excel_row}="","",$B$2-{before})'
                cached = data["scope"]-totals[column-4] if row[column-3] is not None else ""
                sheet.write_formula(excel_row-1, column, formula, derived, cached)
            totals = [totals[i] + (row[i+1] or 0) for i in range(3)]
            actual = data["scope"]-totals[2] if row[3] is not None else ""
            sheet.write_formula(excel_row-1, 6, f'=IF(D{excel_row}="","",$B$2-SUM(D$10:D{excel_row}))', derived, actual)
            sheet.write_formula(excel_row-1, 7, f'=IF(OR(D{excel_row}="",$B$2=0),"",SUM(D$10:D{excel_row})/$B$2)', percent,
                                totals[2]/data["scope"] if row[3] is not None and data["scope"] else "")
        sheet.autofilter(8, 0, max(9, len(data["rows"])+8), 7)
    meta = book.add_worksheet("_metadata")
    meta.write(0, 0, signing.dumps({"schema": 1, "revision": current["revision"], "fingerprint": current["fingerprint"]}, salt=SALT))
    meta.hide()
    book.close()
    return output.getvalue()


def number(value, label, optional=False):
    if value in (None, "") and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError(f"{label}: enter a non-negative whole number.")
    return int(value)


def iso_date(value, label):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label}: enter a valid date (YYYY-MM-DD).") from exc


def validate_table(table, title):
    scope = number(table["scope"], f"{title} / Scope")
    if not scope or not table["rows"]:
        raise ValueError(f"{title}: an enabled sheet needs a positive scope and dated rows.")
    if table["data_date"] > timezone.localdate().isoformat():
        raise ValueError(f"{title}: Data date cannot be in the future.")
    days = [row[0] for row in table["rows"]]
    if len(set(days)) != len(days):
        raise ValueError(f"{title}: duplicate dates are not allowed.")
    if (date.fromisoformat(max(days))-date.fromisoformat(min(days))).days > 3660:
        raise ValueError(f"{title}: the schedule exceeds ten years.")
    for col, label in [(1, "Baseline"), (2, "Lookahead"), (3, "Actual")]:
        if sum(row[col] or 0 for row in table["rows"]) > scope:
            raise ValueError(f"{title}: {label} total exceeds Scope.")
    if any(row[3] is not None and row[0] > table["data_date"] for row in table["rows"]):
        raise ValueError(f"{title}: Actual daily cannot be reported after Data date.")
    if not any(any(value is not None for value in row[1:]) for row in table["rows"]):
        raise ValueError(f"{title}: enter planned or actual quantities.")


def parse_workbook(content, current):
    try:
        content = compact_workbook(content)
        book = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, OSError, KeyError, ParseError) as exc:
        raise ValueError("Choose a valid exported .xlsx workbook.") from exc
    try:
        try:
            meta = signing.loads(book["_metadata"].cell(1, 1).value, salt=SALT)
        except (signing.BadSignature, KeyError, TypeError) as exc:
            raise ValueError("Workbook identity is invalid. Export a new workbook.") from exc
        if meta != {"schema": 1, "revision": current["revision"], "fingerprint": current["fingerprint"]}:
            raise ValueError("Rundown changed since export. Export again and copy your edits into the new workbook.")
        updates, changes, details = {}, [], []
        detail_count = 0
        for key, title in SHEETS.items():
            if title not in book:
                raise ValueError(f"Missing sheet: {title}.")
            sheet = book[title]
            if sheet.max_row > 10010 or sheet.max_column > 8:
                raise ValueError(f"{title}: keep the exported eight columns and at most 10,000 daily rows.")
            if [cell.value for cell in next(sheet.iter_rows(min_row=9, max_row=9, max_col=8))] != HEADERS:
                raise ValueError(f"{title}: keep the exported column headers.")
            enabled = str(sheet.cell(5, 2).value or "").strip().upper()
            if enabled not in ("YES", "NO"):
                raise ValueError(f"{title}: Include on import must be YES or NO.")
            if enabled == "NO":
                continue
            previous = current["tables"][key]
            if sheet.cell(4, 2).value != previous["unit"]:
                raise ValueError(f"{title}: do not change the unit.")
            table = {"enabled": True, "scope": number(sheet.cell(2, 2).value, title+" / Scope"),
                     "data_date": iso_date(sheet.cell(3, 2).value, title+" / Data date"), "unit": previous["unit"], "rows": []}
            for row_index, row in enumerate(sheet.iter_rows(min_row=10, max_col=4, values_only=True), 10):
                if all(value in (None, "") for value in row):
                    continue
                label = f"{title} / row {row_index}"
                table["rows"].append([iso_date(row[0], label), *[number(row[col], label+" / "+HEADERS[col], optional=True) for col in (1,2,3)]])
            table["rows"].sort(key=lambda row: row[0])
            validate_table(table, title)
            if table != previous:
                updates[key] = table
                changes.append({"sheet": title, "before_scope": previous["scope"], "scope": table["scope"],
                                "rows": len(table["rows"]), "actual": sum(row[3] or 0 for row in table["rows"]) if any(row[3] is not None for row in table["rows"]) else None, "data_date": table["data_date"]})
                differences = []
                for field in ("scope", "data_date", "enabled"):
                    if previous[field] != table[field]:
                        differences.append({"day": "Settings", "field": field, "before": previous[field], "after": table[field]})
                before_rows = {row[0]: row for row in previous["rows"]}
                after_rows = {row[0]: row for row in table["rows"]}
                for day in sorted(before_rows.keys() | after_rows.keys()):
                    before = before_rows.get(day, [day, None, None, None])
                    after = after_rows.get(day, [day, None, None, None])
                    for col in (1, 2, 3):
                        if before[col] != after[col]:
                            differences.append({"day": day, "field": HEADERS[col], "before": before[col], "after": after[col]})
                detail_count += len(differences)
                details.extend(dict(item, sheet=title) for item in differences[:max(0, 200-len(details))])
        return {"revision": current["revision"], "fingerprint": current["fingerprint"], "updates": updates,
                "changes": changes, "details": details, "detail_count": detail_count}
    except ParseError as exc:
        raise ValueError("Workbook XML is invalid. Export a new workbook.") from exc
    finally:
        book.close()


def apply_import(parsed, filename, file_hash, user):
    try:
        with transaction.atomic():
            previous = RundownImport.objects.select_for_update().first()
            current = current_state()
            if parsed["revision"] != current["revision"] or parsed["fingerprint"] != current["fingerprint"]:
                raise ValueError("Rundown changed after preview. Export again before importing.")
            if not parsed["updates"]:
                return None
            payload = current["overrides"]
            for key, table in parsed["updates"].items():
                validate_table(table, SHEETS[key])
                payload[key] = table
            return RundownImport.objects.create(base_revision=current["revision"],
                original_filename=Path(filename.replace("\\", "/")).name[:255], file_hash=file_hash,
                imported_by_id=user.pk, payload=payload, metadata={"changes": parsed["changes"]})
    except IntegrityError as exc:
        raise ValueError("Another import was applied. Export the latest workbook and retry.") from exc


def chart_payload(key, table, filename):
    mode, discipline = key.split(":")
    rows = table["rows"]
    scope = table["scope"]
    first, last = date.fromisoformat(rows[0][0]), date.fromisoformat(rows[-1][0])+timedelta(days=1)
    indexed = {row[0]: row for row in rows}
    charts = {name: [] for name in ("dates", "baseline_total", "baseline_rundown", "lookahead_total", "lookahead_rundown", "actual_total", "actual_rundown")}
    totals = [0, 0, 0]
    reported = [any(row[col] is not None for row in rows) for col in (1,2,3)]
    finishes = [None, None]
    point = first
    while point <= last:
        day = point.isoformat()
        row = indexed.get(day, [day, None, None, None])
        charts["dates"].append(day)
        for col, series in [(1,"baseline"),(2,"lookahead")]:
            remaining = scope-totals[col-1]
            charts[f"{series}_total"].append((row[col] or 0) if reported[col-1] else None)
            charts[f"{series}_rundown"].append(remaining if reported[col-1] else None)
            if remaining == 0 and finishes[col-1] is None:
                finishes[col-1] = point
            totals[col-1] += row[col] or 0
        totals[2] += row[3] or 0
        charts["actual_total"].append(row[3])
        charts["actual_rundown"].append(scope-totals[2] if row[3] is not None else None)
        point += timedelta(days=1)
    label = DISCIPLINES[discipline]
    title = "Piping ISO rundown" if key == "fabrication:piping" else f"{label} {mode} rundown"
    return {"available": True, "error": "", "charts": charts,
            "source": {"discipline": discipline, "discipline_label": label, "mode": mode, "mode_label": MODES[mode],
                       "title": title, "unit": table["unit"], "unit_label": table["unit"], "is_sample": False,
                       "data_kind": "real", "snapshot_date": table["data_date"], "snapshot_label": table["data_date"],
                       "managed_by": "rundown_workbook",
                       "workbook": filename, "source_label": "Imported rundown · "+filename,
                       "has_lookahead": reported[1], "has_actual": reported[2], "baseline_label": "Baseline", "lookahead_label": "Lookahead",
                       "notice": "Imported daily quantities. Actual remaining is measured at the end of each reported day; blank actual dates are unreported."},
            "kpis": {"scope_total": scope, "baseline_finish_label": finishes[0].strftime("%d %b %y") if finishes[0] else "—",
                     "lookahead_finish_label": finishes[1].strftime("%d %b %y") if finishes[1] else "—",
                     "finish_variance_days": (finishes[1]-finishes[0]).days if all(finishes) else None,
                     "actual_completed": totals[2], "actual_progress_pct": round(totals[2]/scope*100, 2) if reported[2] else None}}


def overlay_modes(modes):
    batch = RundownImport.objects.first()
    if not batch:
        return modes
    result = deepcopy(modes)
    for key, table in batch.payload.items():
        mode, discipline = key.split(":")
        result[mode]["disciplines"][discipline] = chart_payload(key, table, batch.original_filename)
    return result

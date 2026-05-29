from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any

from django.core.cache import cache
from django.db import transaction

from .models import EngineeringMonitorImport


MONITOR_REQUIRED_HEADERS = {
    "Document Number",
    "Title",
    "Discipline",
    "Revision",
    "Document Status",
    "Issue Status",
}

MONITOR_OFFICIAL_HEADERS = {
    "Documento",
    "Contabilizar",
    "Status normalizado",
}

MONITOR_DISCIPLINE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PMT", ("AA - PROJECT MANAGEMENT",)),
    ("CONSTRUCTION", ("BA - CONSTRUCTION",)),
    ("STRUCTURAL", ("CS - STRUCTURAL",)),
    ("ELECTRICAL", ("EA - ELECTRICAL",)),
    ("TECHNICAL SAFETY", ("HX - HSE", "HS - SAFETY")),
    ("INSTRUMENTATION", ("IN - INSTRUMENTATION",)),
    ("IT / IM", ("JA - IM", "KA - IT")),
    ("PIPING", ("MP - PIPING",)),
    ("MECHANICAL", (
        "MX - OVERAL MECHANICAL",
        "MR - MECHANICAL ROTATING",
        "MS - MECHANICAL STATIC",
        "MH - HVAC",
    )),
    ("PROCESS", ("PX - PROCESS",)),
    ("MATERIALS", ("RA - MATERIALS",)),
)

MONITOR_STATUS_ORDER = (
    "NI",
    "IFR",
    "IFA",
    "IFI",
    "AFC 1",
    "AFC 3",
    "AFC CODE 3A",
    "UNDER REVIEW",
)

_DISCIPLINE_LOOKUP = {
    raw: label
    for label, values in MONITOR_DISCIPLINE_GROUPS
    for raw in values
}
_DISCIPLINE_LABELS = {label for label, _values in MONITOR_DISCIPLINE_GROUPS} | {"PIPING ISOMETRIC"}


def _title_has_isometric_drawing(value: Any) -> bool:
    text = re.sub(r"[^A-Z0-9]+", " ", _norm_text(value))
    return "ISOMETRIC DRAWING" in text


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").strip().split())


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text.upper()).strip()


def _find_sheet(workbook: Any, required_headers: set[str]) -> Any | None:
    normalized_required = {_norm_text(header) for header in required_headers}
    for ws in workbook.worksheets:
        for values in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 5), values_only=True):
            headers = {_norm_text(value).replace("\n", " ") for value in values if _clean_text(value)}
            if normalized_required.issubset(headers):
                return ws
    return None


def _revision_parts(value: Any) -> tuple[str, int]:
    text = _clean_text(value).upper()
    if not text or text == "-":
        return "", 0
    match = re.match(r"([A-Z]+)\s*0*(\d+)?", text)
    if not match:
        return text[:1], 0
    return match.group(1)[:1], int(match.group(2) or 0)


def _issue_code(value: str) -> int | None:
    match = re.search(r"CODE\s*(\d+)", value)
    return int(match.group(1)) if match else None


def _is_not_applicable_document_status(value: str) -> bool:
    text = _norm_text(value)
    return text in {"NAO SE APLICA", "NAO APLICAVEL"} or "NAO APLIC" in text


def _is_excluded_document_number(value: Any) -> bool:
    text = _norm_text(value)
    return "8502" in text or "PVN" in text or "LT" in text


def _is_excluded_title(value: Any) -> bool:
    text = _norm_text(value)
    return "MONTHLY RISK" in text or "3D MODEL REVIEW FILE" in text


def normalize_monitor_discipline(raw_discipline: Any, title: Any = "") -> str:
    text = _norm_text(raw_discipline)
    discipline = _DISCIPLINE_LOOKUP.get(text, "")
    if not discipline and text in _DISCIPLINE_LABELS:
        discipline = text
    if discipline == "PIPING" and _title_has_isometric_drawing(title):
        return "PIPING ISOMETRIC"
    return discipline


def monitor_discipline_order(disciplines: Any = ()) -> list[str]:
    discipline_set = {str(value or "").strip().upper() for value in disciplines if str(value or "").strip()}
    order = [label for label, _values in MONITOR_DISCIPLINE_GROUPS]
    if "PIPING ISOMETRIC" in discipline_set and "PIPING ISOMETRIC" not in order:
        piping_index = order.index("PIPING") + 1 if "PIPING" in order else len(order)
        order.insert(piping_index, "PIPING ISOMETRIC")
    for discipline in sorted(discipline_set):
        if discipline not in order:
            order.append(discipline)
    return order


def _monitor_discipline(raw_discipline: Any, title: Any = "") -> str:
    return normalize_monitor_discipline(raw_discipline, title)


def _status_payload(
    document_status: Any,
    issue_status: Any,
    last_transmittal_purpose: Any,
    fabrication_ref: Any,
    directory: Any,
    document_number: Any,
    revision: Any,
    title: Any,
) -> dict[str, Any]:
    original_doc_status = _clean_text(document_status).upper()
    normalized_doc_status = _norm_text(document_status)
    issue = _norm_text(issue_status)
    purpose = _norm_text(last_transmittal_purpose)
    fabrication = _clean_text(fabrication_ref)
    normalized_directory = _norm_text(directory)
    is_transmittal = normalized_doc_status == "TRANSMITTAL"
    effective_doc_status = "MABU UNDER REVIEW" if is_transmittal else original_doc_status
    code = _issue_code(issue)
    is_afc_afu = "AFC" in issue or "AFU" in issue or purpose.startswith("AFC/AFU")

    def bucket(label: str, group: str, afc_code: str = "") -> dict[str, Any]:
        return {
            "status_bucket": label,
            "doc_status": "MABU UNDER REVIEW" if label == "UNDER REVIEW" else label,
            "doc_status_group": group,
            "afc_code": afc_code,
            "document_status_effective": effective_doc_status,
            "document_status_original": original_doc_status,
            "is_transmittal": is_transmittal,
            "is_countable": True,
            "excluded_reason": "",
        }

    def excluded(reason: str) -> dict[str, Any]:
        return {
            "status_bucket": "",
            "doc_status": "",
            "doc_status_group": "",
            "afc_code": "",
            "document_status_effective": effective_doc_status,
            "document_status_original": original_doc_status,
            "is_transmittal": is_transmittal,
            "is_countable": False,
            "excluded_reason": reason,
        }

    if "VENDOR" in normalized_directory:
        return excluded("Vendor directory")
    if _is_excluded_document_number(document_number):
        return excluded("Excluded document number")
    if _norm_text(revision) == "X":
        return excluded("Cancelled revision X")
    if _is_excluded_title(title):
        return excluded("Excluded title")
    if normalized_doc_status == "CANCELADO":
        return excluded("Not applicable/cancelled")
    if issue.startswith("IFA") or purpose.startswith("IFA") or "ISSUED FOR APPROVAL" in issue or "ISSUED FOR APPROVAL" in purpose:
        return bucket("IFA", "IFA")
    if normalized_doc_status in {"TRANSMITTAL", "ISSUED"} and is_afc_afu and code in {3, 4} and fabrication:
        return bucket("AFC CODE 3A", "AFC", "3A")
    if "REJECTED" in issue:
        return excluded("Rejected")
    if is_afc_afu and code in {1, 2}:
        return bucket("AFC 1", "AFC", "1")
    if is_afc_afu and code in {3, 4}:
        return bucket("AFC 3", "AFC", "3")
    if "APPROVED FOR USE" in issue:
        return bucket("AFC 1", "AFC", "1")
    if issue == "FOE":
        return bucket("AFC 3", "AFC", "3")
    if issue.startswith("IFR") or purpose.startswith("IFR") or "ISSUED FOR REVIEW" in issue or "ISSUED FOR REVIEW" in purpose:
        return bucket("IFR", "IFR")
    if "ISSUED FOR INFORMATION" in issue or purpose.startswith("IFI"):
        return bucket("IFI", "IFI")
    if issue.startswith("NOT ISSUED"):
        return bucket("NI", "NOT ISSUED")
    if _is_not_applicable_document_status(normalized_doc_status):
        return excluded("Not applicable/cancelled")
    if is_transmittal or normalized_doc_status.startswith("ENGINEERING") or normalized_doc_status == "ISSUED":
        return bucket("UNDER REVIEW", "AFC", "UNDER REVIEW")
    return excluded("Unmapped")


def _row_value(raw: dict[str, Any], header: str) -> Any:
    return raw.get(header) or raw.get(_norm_text(header)) or ""


def _first_row_value(raw: dict[str, Any], *headers: str) -> Any:
    for header in headers:
        value = _row_value(raw, header)
        if _clean_text(value):
            return value
    return ""


def _yes(value: Any) -> bool:
    text = _norm_text(value)
    return text in {"SIM", "S", "YES", "Y", "TRUE", "1", "X"}


def _normal_status_bucket(value: Any) -> str:
    text = _norm_text(value)
    text = text.replace("AFC - ", "AFC ")
    text = text.replace("CODE ", "CODE")
    if not text or text in {"NAO", "NO", "DESCONSIDERADO", "EXCLUIDO"}:
        return ""
    if text in {"NI", "NOT ISSUED"}:
        return "NI"
    if text.startswith("IFR"):
        return "IFR"
    if text.startswith("IFA"):
        return "IFA"
    if text in {"IFI", "ISSUED FOR INFORMATION"} or "ISSUED FOR INFORMATION" in text:
        return "IFI"
    if text in {"AFC 1", "AFC CODE1", "AFC CODE 1", "APPROVED FOR USE"}:
        return "AFC 1"
    if text in {"AFC 3", "AFC CODE3", "AFC CODE 3", "FOE"}:
        return "AFC 3"
    if text in {"AFC 3A", "AFC CODE3A", "AFC CODE 3A", "AFC 3 A", "AFC CODE 3 A"}:
        return "AFC CODE 3A"
    if "MABU" in text or "UNDER REVIEW" in text:
        return "UNDER REVIEW"
    return ""


def _status_parts_from_bucket(status_bucket: str) -> tuple[str, str, str]:
    status = _normal_status_bucket(status_bucket)
    if status == "NI":
        return "NI", "NOT ISSUED", ""
    if status in {"IFR", "IFA", "IFI"}:
        return status, status, ""
    if status == "AFC 1":
        return "AFC 1", "AFC", "1"
    if status == "AFC 3":
        return "AFC 3", "AFC", "3"
    if status == "AFC CODE 3A":
        return "AFC CODE 3A", "AFC", "3A"
    if status == "UNDER REVIEW":
        return "MABU UNDER REVIEW", "AFC", "UNDER REVIEW"
    return "", "", ""


def _parse_monitor_rows(ws: Any) -> list[dict[str, Any]]:
    iterator = ws.iter_rows(values_only=True)
    raw_headers = next(iterator)
    headers = [_clean_text(value).replace("\n", " ") for value in raw_headers]
    normalized_headers = [_norm_text(header) for header in headers]
    rows: list[dict[str, Any]] = []

    try:
        for row_number, values in enumerate(iterator, start=2):
            raw = dict(zip(headers, values))
            raw.update(dict(zip(normalized_headers, values)))
            document_number = _clean_text(_row_value(raw, "Document Number"))
            if not document_number:
                continue

            title = _clean_text(_row_value(raw, "Title"))
            revision = _clean_text(_row_value(raw, "Revision")).upper()
            revision_family, revision_number = _revision_parts(revision)
            raw_discipline = _clean_text(_row_value(raw, "Discipline")).upper()
            monitor_discipline = _monitor_discipline(raw_discipline, title)
            status = _status_payload(
                _row_value(raw, "Document Status"),
                _row_value(raw, "Issue Status"),
                _row_value(raw, "Last transmittal purpose"),
                _row_value(raw, "14-Tr_Aol-Fabrication"),
                _row_value(raw, "Directory"),
                document_number,
                revision,
                _row_value(raw, "Title"),
            )
            is_monitored = bool(monitor_discipline)
            rows.append({
                "row_number": row_number,
                "document_number": document_number,
                "title": title,
                "directory": _clean_text(_row_value(raw, "Directory")),
                "discipline": monitor_discipline or raw_discipline or "-",
                "source_discipline": raw_discipline or "-",
                "is_monitored": is_monitored,
                "revision": revision,
                "revision_family": revision_family,
                "revision_number": revision_number,
                "issue_status": _clean_text(_row_value(raw, "Issue Status")).upper(),
                "last_transmittal_purpose": _clean_text(_row_value(raw, "Last transmittal purpose")).upper(),
                "fabrication_ref": _clean_text(_row_value(raw, "14-Tr_Aol-Fabrication")),
                **status,
            })
    except ValueError:
        if not rows or len(rows) + 1 < int(getattr(ws, "max_row", 0) or 0):
            raise
    return rows


def _parse_official_rows(ws: Any) -> list[dict[str, Any]]:
    iterator = ws.iter_rows(values_only=True)
    raw_headers = next(iterator)
    headers = [_clean_text(value).replace("\n", " ") for value in raw_headers]
    normalized_headers = [_norm_text(header) for header in headers]
    rows: list[dict[str, Any]] = []

    for row_number, values in enumerate(iterator, start=2):
        raw = dict(zip(headers, values))
        raw.update(dict(zip(normalized_headers, values)))
        document_number = _clean_text(_first_row_value(raw, "Documento", "Document Number"))
        if not document_number:
            continue

        title = _clean_text(_first_row_value(raw, "Titulo", "Título", "Title"))
        revision = _clean_text(_first_row_value(raw, "Revisao", "Revisão", "Revision", "rev")).upper()
        revision_family, revision_number = _revision_parts(revision)
        source_discipline = _clean_text(_first_row_value(raw, "Disciplina origem", "Source Discipline", "Discipline")).upper()
        raw_discipline = _clean_text(_first_row_value(raw, "Disciplina", "Disciplina AOL", "Discipline")).upper()
        discipline = (
            normalize_monitor_discipline(source_discipline or raw_discipline, title)
            or normalize_monitor_discipline(raw_discipline, title)
            or raw_discipline
        )
        status_bucket = _normal_status_bucket(_first_row_value(raw, "Status normalizado", "Status AOL", "Status", "Final Status"))
        is_countable = _yes(_first_row_value(raw, "Contabilizar", "Count", "Considerar")) and bool(status_bucket)
        doc_status, doc_status_group, afc_code = _status_parts_from_bucket(status_bucket)
        document_status_original = _clean_text(_first_row_value(raw, "Status documento", "Document Status")).upper()
        is_transmittal = _norm_text(document_status_original) == "TRANSMITTAL"
        document_status_effective = "MABU UNDER REVIEW" if is_transmittal else document_status_original
        excluded_reason = _clean_text(_first_row_value(raw, "Motivo desconsiderado", "Motivo", "Excluded Reason"))
        if not is_countable and not excluded_reason:
            excluded_reason = "Desconsiderado pelo administrador"

        rows.append({
            "row_number": row_number,
            "document_number": document_number,
            "title": title,
            "directory": _clean_text(_first_row_value(raw, "Diretorio", "Diretório", "Directory")),
            "discipline": discipline or source_discipline or "-",
            "source_discipline": source_discipline or discipline or "-",
            "is_monitored": True,
            "revision": revision,
            "revision_family": revision_family,
            "revision_number": revision_number,
            "issue_status": _clean_text(_first_row_value(raw, "Issue Status", "Status emissao", "Status emissão")).upper(),
            "last_transmittal_purpose": _clean_text(_first_row_value(raw, "Last transmittal purpose", "Proposito transmittal", "Propósito transmittal")).upper(),
            "fabrication_ref": _clean_text(_first_row_value(raw, "14-Tr_Aol-Fabrication", "Fabrication")),
            "status_bucket": status_bucket if is_countable else "",
            "doc_status": doc_status if is_countable else "",
            "doc_status_group": doc_status_group if is_countable else "",
            "afc_code": afc_code if is_countable else "",
            "document_status_effective": document_status_effective,
            "document_status_original": document_status_original,
            "is_transmittal": is_transmittal,
            "is_countable": is_countable,
            "excluded_reason": "" if is_countable else excluded_reason,
        })
    return rows


def import_engineering_monitor_workbook(uploaded_file: Any, *, imported_by: Any = None) -> EngineeringMonitorImport:
    filename = Path(getattr(uploaded_file, "name", "") or "engineering-monitor.xlsx").name
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise ValueError("Upload an engineering monitor workbook in .xlsx or .xlsm format.")

    content = uploaded_file.read()
    if not content:
        raise ValueError("The uploaded engineering monitor workbook is empty.")

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
    official_ws = workbook["Base Engenharia"] if "Base Engenharia" in workbook.sheetnames else workbook["Base AOL"] if "Base AOL" in workbook.sheetnames else _find_sheet(workbook, MONITOR_OFFICIAL_HEADERS)
    detail_ws = None
    import_mode = "official_aol" if official_ws is not None else "raw_engineering"
    if official_ws is None:
        detail_ws = workbook["Sheet1"] if "Sheet1" in workbook.sheetnames else _find_sheet(workbook, MONITOR_REQUIRED_HEADERS)
    if detail_ws is None:
        if official_ws is None:
            raise ValueError("The document detail sheet was not found in the monitor workbook.")

    rows = _parse_official_rows(official_ws) if official_ws is not None else _parse_monitor_rows(detail_ws)
    if not rows:
        raise ValueError("No valid documents were found in the monitor workbook.")

    monitored_rows = [row for row in rows if row["is_monitored"]]
    countable_rows = [row for row in monitored_rows if row["is_countable"]]
    excluded_rows = [row for row in monitored_rows if not row["is_countable"]]
    status_counts = Counter(row["status_bucket"] for row in countable_rows)
    excluded_counts = Counter(row["excluded_reason"] for row in excluded_rows)
    discipline_counts = Counter(row["discipline"] for row in countable_rows)
    source_discipline_counts = Counter(row["source_discipline"] for row in rows)

    file_hash = hashlib.sha256(content).hexdigest()
    user = getattr(imported_by, "_wrapped", imported_by)
    if not getattr(user, "is_authenticated", False):
        user = None

    discipline_order = monitor_discipline_order(discipline_counts)

    payload = {
        "documents": rows,
        "status_order": list(MONITOR_STATUS_ORDER),
        "discipline_order": discipline_order,
        "import_mode": import_mode,
    }

    with transaction.atomic():
        EngineeringMonitorImport.objects.filter(is_active=True).update(is_active=False)
        batch = EngineeringMonitorImport.objects.create(
            original_filename=filename,
            file_size=len(content),
            file_hash=file_hash,
            imported_by=user,
            detail_sheet=(official_ws or detail_ws).title,
            document_count=len(rows),
            monitored_document_count=len(countable_rows),
            discipline_count=len(discipline_counts),
            excluded_count=len(excluded_rows),
            payload=payload,
            metadata={
                "sheet_names": workbook.sheetnames,
                "total_sheet_count": len(workbook.sheetnames),
                "import_mode": import_mode,
                "raw_document_count": len(rows),
                "monitored_raw_document_count": len(monitored_rows),
                "status_counts": dict(status_counts),
                "excluded_counts": dict(excluded_counts),
                "source_discipline_counts": dict(source_discipline_counts),
                "discipline_counts": dict(discipline_counts),
            },
        )

    cache.clear()
    return batch

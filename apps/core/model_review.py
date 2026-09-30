"""Read-only drawing/line index using the same fabrication progress as S03."""
from __future__ import annotations

import re
from collections import defaultdict

from .fabrication_source import _as_dict, _weekly_overall_value, overall_value, stage_value, stage_is_applicable, STAGE_KEYS


def line_key(value):
    tag = re.sub(r"\s+", "", str(value or "").strip().lstrip("/")).upper()
    # The model may quote a numeric class (e.g. -"750"-); inch marks,
    # fractional diameters and branch suffixes remain part of the exact tag.
    return re.sub(r'-"(\d+)"(?=-|$)', r'-\1', tag)


def line_tags(value):
    return list(dict.fromkeys(
        text.strip() for text in re.split(r"[,;\n\r]+", str(value or ""))
        if line_key(text) not in {"", "-", "N/A", "NA", "NONE"}
    ))


def document_line_tags(document):
    tags = line_tags(document.get("piping_line_number"))
    drawing_number = str(document.get("drawing_number") or "").strip()
    if len(tags) != 1 or not drawing_number:
        return tags
    stored_key = line_key(tags[0])
    rows = str(document.get("raw_text") or "").splitlines()
    rows = [row.strip() for row in rows]
    candidates = {}
    for index in range(len(rows) - 4):
        if rows[index + 4] != drawing_number:
            continue
        candidate = rows[index]
        match = re.fullmatch(r'TAM26-TP-?\d+[A-Z]*(?:/\d+[A-Z]*)*-(.+)', candidate, re.IGNORECASE)
        if not match:
            continue
        sheet, total, pipe_class = rows[index + 1:index + 4]
        if not (re.fullmatch(r"[1-9]\d*", sheet) and re.fullmatch(r"[1-9]\d*", total)
                and int(sheet) <= int(total) and re.fullmatch(r"[A-Z][A-Z0-9]*", pipe_class, re.IGNORECASE)):
            continue
        # Only the drawing's title block can restore an authored tie-in tag.
        # CONT./CONN. references elsewhere in the PDF must not become links.
        suffix = line_key(match.group(1))
        if suffix == stored_key or suffix.startswith(stored_key + "/"):
            candidates.setdefault(line_key(candidate), candidate)
    return list(candidates.values()) if len(candidates) == 1 else tags


def package_state(package):
    stages = _as_dict(package.get("stages"))
    progress = overall_value(stages)
    weekly = _weekly_overall_value(stages)
    applicable = [key for key in STAGE_KEYS if stage_is_applicable(stages, key)]
    complete = weekly >= 100 if weekly is not None else bool(applicable) and all(stage_value(stages, key) >= 100 for key in applicable)
    if complete:
        return "completed"
    if progress > 0 or package.get("actual_start") or any(stage_value(stages, key) > 0 for key in STAGE_KEYS):
        return "started"
    return "not_started"


def aggregate_status(states):
    if states and all(value == "completed" for value in states):
        return "completed"
    if any(value in {"started", "completed"} for value in states):
        return "started"
    if not states or "unlinked" in states:
        return "unlinked"
    return "not_started"


def review_discipline(value):
    value = str(value or "").strip().lower()
    return {"piping": "piping", "tubulação": "piping", "tubulacao": "piping",
            "structural": "structural", "structure": "structural", "estrutura": "structural",
            "electrical": "electrical", "elétrica": "electrical", "eletrica": "electrical",
            "instrumentation": "instrumentation", "instrumentação": "instrumentation",
            "instrumentacao": "instrumentation"}.get(value, "other")


def build_review(documents, packages):
    by_document = defaultdict(list)
    for package in packages:
        if package.get("document_id"):
            by_document[(package["document_id"], review_discipline(package.get("discipline")))].append(package_state(package))
    drawings = []
    by_line = {}
    for doc in documents:
        tags = document_line_tags(doc)
        discipline = review_discipline(doc.get("discipline")) if doc.get("discipline") else ("piping" if tags else "other")
        if discipline != "piping":
            tags = []
        states = by_document.get((doc["id"], discipline), [])
        status = aggregate_status(states)
        drawings.append({"id": str(doc["id"]), "name": doc.get("drawing_number") or str(doc["id"]),
                         "title": doc.get("title") or "", "discipline": discipline, "lines": tags, "status": status})
        for tag in tags:
            line = by_line.setdefault(line_key(tag), {"tag": tag, "states": [], "drawing_ids": []})
            line["states"].extend(states or ["unlinked"])
            line["drawing_ids"].append(str(doc["id"]))
    lines = [{"key": key, "tag": line["tag"], "status": aggregate_status(line["states"]),
              "drawing_ids": line["drawing_ids"], "unlinked": "unlinked" in line["states"]}
             for key, line in sorted(by_line.items())]
    return {"available": True, "drawings": drawings, "lines": lines,
            "source": "DATAFY / SPDM fabrication", "completion_rule": "All linked packages at 100%; no unlinked drawings"}


def review_payload():
    from .real_sources import _datafy_conn, _rows
    with _datafy_conn() as conn:
        cur = conn.cursor()
        documents = _rows(cur, """
            select id, drawing_number, title, discipline, piping_line_number, raw_text
            from core_document
            order by drawing_number, id
        """)
        packages = _rows(cur, """
            select document_id, discipline, stages, actual_start
            from fabrication_fabricationpackage where is_active = true
        """)
    return build_review(documents, packages)

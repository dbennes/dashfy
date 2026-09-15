"""Read DATAFY's canonical Drawings scope without changing source records.

Revision ordering mirrors ``catalog.document_versions`` and
``extraction.services.compare_revision_codes`` in DATAFY. Blank-table matching
mirrors ``catalog.drawings.duplicate_blank_table_ids``. Keep these rules in sync
with their source helpers: a later upload alone does not define a revision.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
import re


_REVISION_PATTERN = re.compile(r"([A-Z])\s*0*(\d{1,3})", re.IGNORECASE)
_REVISION_LETTER_RANK = {"R": 10, "A": 20, "B": 25, "C": 30}


def _normalize_revision(raw: str) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    if not raw:
        return ""
    match = _REVISION_PATTERN.search(raw)
    if match:
        letter, digits = match.group(1).upper(), match.group(2)
        return f"{letter}{'0' + digits if len(digits) == 1 else digits}"
    digits = "".join(char for char in raw if char.isdigit())
    if digits and digits == raw:
        return "0" + digits if len(digits) == 1 else digits
    return raw.upper()


def _revision_sort_key(raw: str) -> tuple:
    revision = _normalize_revision(raw)
    if not revision:
        return (0, 0, 0, "")
    match = _REVISION_PATTERN.fullmatch(revision)
    if match:
        letter = match.group(1).upper()
        rank = _REVISION_LETTER_RANK.get(letter, 40 + max(0, ord(letter) - ord("A")))
        return (2, rank, int(match.group(2)), revision)
    if revision.isdigit():
        return (1, 0, int(revision), revision)
    return (1, 0, 0, revision)


def _candidate_is_newer(candidate: dict, current: dict) -> bool:
    candidate_revision = _revision_sort_key(candidate.get("revision") or "")
    current_revision = _revision_sort_key(current.get("revision") or "")
    if candidate_revision != current_revision:
        return candidate_revision > current_revision
    candidate_uploaded = candidate.get("uploaded_at")
    current_uploaded = current.get("uploaded_at")
    if candidate_uploaded and current_uploaded and candidate_uploaded != current_uploaded:
        return candidate_uploaded > current_uploaded
    return int(candidate.get("pk") or 0) > int(current.get("pk") or 0)


def _canonical_excluded_document_ids(ready_rows: list[dict]) -> set[int]:
    winners: dict[tuple, dict] = {}
    for row in ready_rows:
        drawing = re.sub(r"\s+", " ", str(row.get("drawing_number") or "").strip().upper())
        key = f"DRAWING:{drawing}" if drawing else f"DOCUMENT:{int(row['pk'])}"
        group = (int(row["project_id"]), key)
        current = winners.get(group)
        if current is None or _candidate_is_newer(row, current):
            winners[group] = row
    return {int(row["pk"]) for row in ready_rows} - {
        int(row["pk"]) for row in winners.values()
    }


def _text_key(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def _quantity_key(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = Decimal(text)
    except Exception:
        return text
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") or "0"


def _description_similarity(left: str, right: str) -> float:
    left_key, right_key = _text_key(left), _text_key(right)
    if not left_key or not right_key:
        return 0
    if left_key == right_key:
        return 1
    if len(left_key) > 12 and len(right_key) > 12 and (
        left_key.startswith(right_key) or right_key.startswith(left_key)
    ):
        return 0.97
    return SequenceMatcher(None, left_key, right_key).ratio()


def _rows_match(left: dict, right: dict) -> bool:
    for field, normalizer in (
        ("item_number", _text_key), ("quantity", _quantity_key), ("unit", _text_key),
    ):
        left_key, right_key = normalizer(left.get(field)), normalizer(right.get(field))
        if left_key and right_key and left_key != right_key:
            return False
    return _description_similarity(left.get("description"), right.get("description")) >= 0.88


def _item_number_qty_unit_keys(items: list[dict]) -> set[tuple]:
    keys = set()
    for item in items:
        item_number = _text_key(item.get("item_number"))
        if not item_number:
            return set()
        keys.add((item_number, _quantity_key(item.get("quantity")), _text_key(item.get("unit"))))
    return keys


def _is_duplicate_blank_table(blank_items: list[dict], named_items: list[dict]) -> bool:
    if not blank_items or not named_items:
        return False
    used_named_rows: set[int] = set()
    matched = 0
    for blank_item in blank_items:
        best_index, best_similarity = None, -1.0
        for index, named_item in enumerate(named_items):
            if index in used_named_rows or not _rows_match(blank_item, named_item):
                continue
            similarity = _description_similarity(blank_item.get("description"), named_item.get("description"))
            if similarity > best_similarity:
                best_index, best_similarity = index, similarity
        if best_index is not None:
            used_named_rows.add(best_index)
            matched += 1
    if matched == len(blank_items):
        return True
    if len(blank_items) < 5 or matched < max(1, int(len(blank_items) * 0.8)):
        return False
    blank_keys = _item_number_qty_unit_keys(blank_items)
    named_keys = _item_number_qty_unit_keys(named_items)
    return bool(blank_keys and named_keys and blank_keys.issubset(named_keys))


def _read_rows(cursor, query: str, params: tuple = ()) -> list[dict]:
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def supply_scope_exclusions(conn) -> dict[str, set[int]]:
    """Return obsolete document IDs and duplicate blank-table IDs to exclude.

    ``conn`` uses DASHFY's DATAFY connection adapter (dictionary rows and ``?``
    parameters). Only SELECTs are issued. Unprocessed uploads remain visible;
    an extracted empty revision can supersede previous material-filled ones.
    Material descriptions are read only for pages containing an unnamed table.
    """
    cursor = conn.cursor()
    ready_rows = _read_rows(cursor, """
        select d.id as pk, d.project_id, d.drawing_number, d.revision, d.uploaded_at
        from core_document d
        where exists (
            select 1 from core_extractedtable t
            join core_materialitem mi on mi.table_id = t.id
            where t.document_id = d.id
        ) or (
            d.status in ('success', 'review')
            and (d.processed_at is not null or d.extraction_method <> '')
        )
    """)
    excluded_docs = _canonical_excluded_document_ids(ready_rows)
    tables = [row for row in _read_rows(cursor, """
        select id, document_id, name, page_number from core_extractedtable
    """) if int(row["document_id"]) not in excluded_docs]
    blank_pages = {
        (int(table["document_id"]), int(table["page_number"] or 1))
        for table in tables if not str(table["name"] or "").strip()
    }
    candidates = [table for table in tables if (
        int(table["document_id"]), int(table["page_number"] or 1)
    ) in blank_pages]
    items_by_table: dict[int, list[dict]] = defaultdict(list)
    candidate_ids = [int(table["id"]) for table in candidates]
    for offset in range(0, len(candidate_ids), 1000):
        ids = candidate_ids[offset:offset + 1000]
        placeholders = ", ".join("?" for _ in ids)
        for item in _read_rows(cursor, f"""
            select table_id, item_number, description, quantity, unit
            from core_materialitem where table_id in ({placeholders})
            order by row_order, id
        """, tuple(ids)):
            items_by_table[int(item["table_id"])].append(item)
    named_by_page: dict[tuple, list[list[dict]]] = defaultdict(list)
    for table in candidates:
        if str(table["name"] or "").strip() and items_by_table.get(int(table["id"])):
            named_by_page[(int(table["document_id"]), int(table["page_number"] or 1))].append(
                items_by_table[int(table["id"])]
            )
    excluded_tables: set[int] = set()
    for table in candidates:
        if str(table["name"] or "").strip():
            continue
        blank_items = items_by_table.get(int(table["id"]), [])
        if any(_is_duplicate_blank_table(blank_items, named_items) for named_items in named_by_page.get(
            (int(table["document_id"]), int(table["page_number"] or 1)), []
        )):
            excluded_tables.add(int(table["id"]))
    return {"document_ids": excluded_docs, "table_ids": excluded_tables}

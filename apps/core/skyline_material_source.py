"""Whole-line material lights from the existing, read-only DATAFY integration.

PO coverage is not a yard receipt. Piping spool progress is not support progress.
These distinctions are shared with Supply/Fabrication rather than inferred from
the skyline's schedule or from the user's currently filtered material table.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import re
from typing import Any, Iterable

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import fabrication_source as fabrication
from . import real_sources as supply

logger = logging.getLogger(__name__)
CATEGORIES = ("supports", "erection", "valves")
SOURCE = "DATAFY · current drawings / material allocations / actual yard receipts"

# The skyline stores size/service/line number; DATAFY additionally stores the
# schedule and piping specification. Parse that schema, never a substring.
_LINE_ID = re.compile(r'^(\d+(?:-\d+/\d+|/\d+)?)"-([A-Z]{2})-(\d{6})(?:-[A-Z0-9.]+)*$')


def line_identity(value: Any) -> str:
    text = str(value or "").strip().upper().replace("″", '"').replace("”", '"')
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^(\d+)\.(\d+/\d+)\"", r'\1-\2"', text)
    match = _LINE_ID.fullmatch(text)
    if match:
        return f'{match[1]}"-{match[2]}-{match[3]}'
    return text if text not in {"", "-", "N/A", "NA"} else ""


_DOCUMENTS_SQL = """
select d.id as document_id, d.project_id, d.piping_line_number as line,
       d.drawing_number, d.revision, d.status, d.field_complete,
       d.field_complete_at,
       exists(select 1 from core_extractedtable t
              join core_materialitem mi on mi.table_id = t.id
              where t.document_id = d.id) as has_materials
  from core_document d
 where trim(coalesce(d.piping_line_number, '')) <> ''
   and (trim(coalesce(d.drawing_number, '')) = '' or not exists (
       select 1 from core_document newer_d
        where newer_d.project_id = d.project_id
          and lower(newer_d.drawing_number) = lower(d.drawing_number)
          and (newer_d.uploaded_at > d.uploaded_at or
               (newer_d.uploaded_at = d.uploaded_at and newer_d.id > d.id))
          and exists(select 1 from core_extractedtable newer_t
                     join core_materialitem newer_mi on newer_mi.table_id = newer_t.id
                     where newer_t.document_id = newer_d.id)))
 order by d.id
"""

_MATERIAL_FAMILIES_SQL = """
with match_one as (
    select material_item_id, min(catalog_item_id) as catalog_item_id
      from catalog_catalogmatch where material_item_id is not null
     group by material_item_id
)
select mi.id as material_item_id, mi.category,
       coalesce(mf.name_en, '') as family
  from core_materialitem mi
  join core_extractedtable t on t.id = mi.table_id
  left join match_one cm on cm.material_item_id = mi.id
  left join catalog_catalogitem ci on ci.id = cm.catalog_item_id
  left join catalog_materialfamily mf on mf.id = ci.family_id
 where t.document_id = any(?)
"""

_ALLOCATIONS_SQL = """
select a.material_item_id, a.id as allocation_id, a.qty_allocated,
       poi.id as po_item_id, poi.line_number as po_line_number, poi.description as po_description,
       poi.product_code, poi.raw_row, poi.extra_fields as po_extra_fields,
       po.id as po_id, po.po_number, po.procurement_plan_stage, po.procurement_plan_kind,
       po.procurement_plan_date, po.procurement_plan_payload
  from catalog_allocation a
  join core_materialitem mi on mi.id = a.material_item_id
  join core_extractedtable t on t.id = mi.table_id
  join catalog_stockpiece sp on sp.id = a.stock_piece_id
  join core_purchaseorderitem poi on poi.id = sp.po_item_id
  join core_purchaseorder po on po.id = poi.purchase_order_id
 where t.document_id = any(?)
"""

_PO_IDENTITIES_SQL = "select id as po_id, po_number from core_purchaseorder"
_PO_ITEM_IDENTITIES_SQL = """
select id as po_item_id, purchase_order_id as po_id, line_number, description
  from core_purchaseorderitem where purchase_order_id = any(?)
"""

_SUPPORT_RELATIONS_SQL = """
select to_regclass('public.catalog_drawingsupport') as supports,
       to_regclass('public.catalog_componenttagreading') as readings,
       to_regclass('public.catalog_drawingcomponenttag') as component_tags
"""
_SUPPORTS_SQL = """
select id, document_id, support_reference, support_mark
  from catalog_drawingsupport where document_id = any(?)
"""
_READINGS_SQL = """
select document_id, extractor_version, supports_found, read_at
  from catalog_componenttagreading where document_id = any(?)
"""
_VALVE_TAGS_SQL = """
select distinct tag.document_id, tag.material_item_id
  from catalog_drawingcomponenttag tag
  join core_materialitem mi on mi.id = tag.material_item_id
  join core_extractedtable t on t.id = mi.table_id and t.document_id = tag.document_id
 where tag.document_id = any(?) and tag.category = 'valve'
   and tag.source in ('balloon_box', 'balloon_column', 'tag_box', 'table_code', 'manual')
"""


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _category(row: dict[str, Any]) -> str | None:
    """A U-bolt used as a pipe support must not turn into an erection bolt."""
    if supply._supply_normalize_scope(row.get("scope"), row.get("table_name")) == "other":
        return None
    # PSV / relief valves are sometimes catalogued as Instrument. DATAFY's
    # exact physical component tag-to-MTO link is authoritative for those rows.
    if row.get("component_category") == "valve":
        return "valves"
    category = str(row.get("category") or "").strip().upper()
    family = str(row.get("family") or "").strip().upper()
    if category in {"SUPPORT", "SUPPORTS"} or family in {
        "PIPE SUPPORT / SHOE / GUIDE", "PIPE TRUNNION", "U-BOLT",
    }:
        return "supports"
    if category in {"BOLT", "BOLTS", "GASKET", "GASKETS"} or family in {
        "BOLT", "STUD BOLT", "NUT", "WASHER", "GASKET",
    }:
        return "erection"
    if category in {"VALVE", "VALVES"} or family == "VALVE":
        return "valves"
    return None


def _evidence(status: str, observed_on: date, note: str, **counts: Any) -> dict[str, Any]:
    return {
        "status": status, "source": SOURCE, "as_of_date": observed_on.isoformat(),
        "note": note, "counts": counts,
    }


def _field_complete(document: dict[str, Any], observed_on: date) -> bool:
    completed_on = _date(document.get("field_complete_at"))
    return bool(document.get("field_complete") and completed_on and completed_on <= observed_on)


def _po_identity(value: Any) -> str:
    raw = str(value or "")
    text = raw.upper().translate(str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX"))
    normalized = re.sub(r"[^A-Z0-9]", "", text)
    if re.search(r"PO[\s._-]*[Оо][\s._-]*[Нн]", raw, re.IGNORECASE):
        normalized = re.sub(r"^(AVE(?:125|126))POOH(\d{5})$", r"\1POH\2", normalized)
    return re.sub(r"^(AVE(?:125|126)POH\d{5})REV(?:ISION)?\d+[A-Z]*$", r"\1", normalized)


def _po_line_identity(value: Any) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return str(int(Decimal(text)))
    return re.sub(r"\s+", "", text)


def _arrived_date(value: Any) -> str:
    iso = supply._expected_date_iso(str(value or ""))
    return iso if iso and iso <= timezone.localdate().isoformat() else ""


def _actual_dates(payload: dict) -> list[str]:
    candidates = [payload, *(payload.get("timeline") or [])]
    return [iso for row in candidates if isinstance(row, dict)
            and supply._is_delivery_at_yard_actual(row.get("stage"), row.get("kind"))
            for iso in [_arrived_date(row.get("date"))] if iso]


def _plan_tags(value: Any) -> set[str]:
    text = re.sub(r"\s*-\s*", "-", str(value or "").upper())
    return set(re.findall(r"(?<![\w\-/])\d{2,3}-[A-Z]{1,6}-\d{1,5}[A-Z]?(?![\w-])", text))


def _parent_consensus(row: dict, unique_po: bool) -> dict | None:
    parent = fabrication._as_dict(row.get("procurement_plan_payload")).get("daily_plan")
    if not isinstance(parent, dict) or not unique_po or parent.get("source_type") != "daily_procurement_plan":
        return None
    if _po_identity(parent.get("po_number_in_plan")) != _po_identity(row.get("po_number")):
        return None
    source_rows = parent.get("source_rows") or []
    unscoped = bool(source_rows) and all(
        isinstance(lot, dict) and not (lot.get("has_item_reference") or lot.get("line_numbers") or lot.get("tags"))
        and not re.search(r"\b(?:line\s*(?:items?)?|items?)\b", str(lot.get("designation") or ""), re.IGNORECASE)
        for lot in source_rows
    )
    scope = parent.get("item_scope") or ""
    if scope != "po_consensus" and not (unscoped and (not scope or (scope == "item_match" and parent.get("conflicting_lots")))):
        return None
    # Same latest-source-date resolution as DATAFY; conflicting same-date
    # states are conservatively left pending instead of selecting a sibling.
    options = [option for option in parent.get("current_options") or [] if isinstance(option, dict)]
    current = parent.get("current")
    if isinstance(current, dict):
        options = [*options, current]
    keys = {(str(option.get("stage") or ""), str(option.get("kind") or ""), str(option.get("date") or "")[:10])
            for option in options if _date(option.get("date")) and option.get("stage") and option.get("kind")}
    latest = max((key[2] for key in keys), default="")
    selected = [key for key in keys if key[2] == latest]
    if len(selected) != 1:
        return None
    available = {(str(option.get("stage") or ""), str(option.get("kind") or ""), str(option.get("date") or "")[:10])
                 for option in [*(parent.get("timeline") or []), *(parent.get("current_options") or [])]
                 if isinstance(option, dict)}
    if selected[0] not in available:
        return None
    stage, kind, selected_date = selected[0]
    return dict(parent, stage=stage, kind=kind, date=selected_date)


def _allocation_receipt_date(row: dict, po_ids: dict, item_ids: dict) -> str:
    """Exact-item evidence, following DATAFY catalog.drawings precedence.

    An empty item tracker is authoritative. A parent's newest Actual cannot
    be inherited by sibling items. Stale/ambiguous daily mappings stay pending.
    """
    extra = fabrication._as_dict(row.get("po_extra_fields"))
    raw = fabrication._as_dict(row.get("raw_row"))
    placeholder = row.get("product_code") == "PIPE_SUPPORT_TRACKING" or raw.get("tracking_rule") == "PIPE_SUPPORT_PIPING_PO"
    if not placeholder and supply._supply_row_has_parallel_yard_po(row):
        return timezone.localdate().isoformat()
    tracker = extra.get("procurement_tracker")
    if isinstance(tracker, dict):
        return _arrived_date(tracker.get("yard_actual"))
    if raw.get("_procurement_tracker"):
        return _arrived_date(raw.get("Delivery At Yard Actual") or raw.get("Delivered at Final Location"))
    identity = _po_identity(row.get("po_number"))
    unique_po = bool(identity and po_ids.get(identity) == {row.get("po_id")})
    daily = extra.get("daily_procurement_plan")
    if isinstance(daily, dict):
        valid_base = (
            unique_po and daily.get("source_type") == "daily_procurement_plan"
            and not daily.get("ambiguous") and not daily.get("partial_actual")
            and str(daily.get("purchase_order_id")) == str(row.get("po_id"))
            and _po_identity(daily.get("po_number_in_plan")) == identity
        )
        mapping = daily.get("mapping")
        valid = False
        if valid_base and mapping == "explicit_line":
            key = _po_line_identity(daily.get("line_number"))
            valid = bool(key and key == _po_line_identity(row.get("po_line_number"))
                         and item_ids.get((row.get("po_id"), key)) == {row.get("po_item_id")})
        elif valid_base and mapping == "exact_unique_tag":
            tags = {str(tag).strip().upper() for tag in daily.get("matched_tags") or []}
            valid = any(item_ids.get((row.get("po_id"), "tag:" + tag)) == {row.get("po_item_id")}
                        for tag in tags.intersection(_plan_tags(row.get("po_description"))))
        elif valid_base and mapping == "exact_po_consensus":
            consensus = _parent_consensus(row, unique_po)
            valid = bool(consensus and all(str(daily.get(field) or "") == str(consensus.get(field) or "")
                                          for field in ("stage", "kind", "date")))
        return max(_actual_dates(daily), default="") if valid else ""
    consensus = _parent_consensus(row, unique_po)
    if consensus is not None:
        return max(_actual_dates(consensus), default="") if not consensus.get("partial_actual") else ""
    parent = fabrication._as_dict(row.get("procurement_plan_payload")).get("daily_plan")
    if not isinstance(parent, dict) or not unique_po:
        return ""
    if parent.get("source_type") != "daily_procurement_plan" or _po_identity(parent.get("po_number_in_plan")) != identity:
        return ""
    source_rows = parent.get("source_rows") or []
    dates = []
    for source_row in source_rows:
        if not isinstance(source_row, dict) or source_row.get("has_item_reference") or source_row.get("line_numbers") or source_row.get("tags"):
            return ""
        if re.search(r"\b(?:line\s*(?:items?)?|items?)\b", str(source_row.get("designation") or ""), re.IGNORECASE):
            return ""
        # Every independent PO-wide lot must have one dated actual receipt.
        actuals = {iso for milestone in source_row.get("timeline") or []
                   if isinstance(milestone, dict)
                   and supply._is_delivery_at_yard_actual(milestone.get("stage"), milestone.get("kind"))
                   for iso in [supply._expected_date_iso(str(milestone.get("date") or ""))] if iso}
        if len(actuals) != 1:
            return ""
        dates.append(actuals.pop())
    return _arrived_date(max(dates, default=""))


def enrich_material_receipts(
    materials: list[dict], allocations: list[dict],
    po_identity_rows: list[dict] | None = None, item_identity_rows: list[dict] | None = None,
) -> None:
    """Use Supply's quantity rules, excluding temporary support coverage POs.

    DATAFY creates PIPE_SUPPORT_TRACKING placeholders solely to cover the PO
    requirement. Unlike genuine parallel-supply receipts, their PO name is not
    physical evidence. An actual dated yard milestone still qualifies normally.
    """
    po_ids: dict[Any, set] = defaultdict(set)
    item_ids: dict[Any, set] = defaultdict(set)
    for row in po_identity_rows or []:
        po_ids[_po_identity(row.get("po_number"))].add(row["po_id"])
    for row in item_identity_rows or []:
        item_ids[(row["po_id"], _po_line_identity(row.get("line_number")))].add(row["po_item_id"])
        for tag in _plan_tags(row.get("description")):
            item_ids[(row["po_id"], "tag:" + tag)].add(row["po_item_id"])
    receipt_rows = []
    for allocation in allocations:
        row = dict(allocation)
        actual = _allocation_receipt_date(row, po_ids, item_ids)
        row.update(po_number="", po_numbers="", procurement_plan_payload={},
                   procurement_plan_stage="Delivery at yard", procurement_plan_kind="Actual",
                   procurement_plan_date=actual)
        receipt_rows.append(row)
    yard_ids = supply._supply_fully_at_yard_material_ids(materials, receipt_rows)
    yard_qty = supply._supply_yard_allocation_qty_by_material(receipt_rows)
    po_ids = {row["material_item_id"] for row in allocations}
    supply._supply_enrich_material_rows(materials, yard_ids, po_ids)
    for row in materials:
        row["yard_qty"] = float(yard_qty.get(row["material_item_id"], Decimal(0)))


def _material_result(
    items: list[dict[str, Any]], documents: list[dict[str, Any]], observed_on: date,
) -> dict[str, Any]:
    docs_by_id = {row["document_id"]: row for row in documents}
    complete_scope = all(row.get("status") == "success" and row.get("has_materials") for row in documents)
    total = len(items)
    ready = received = invalid = 0
    with_po = fully_allocated = partly_allocated = 0
    for row in items:
        requested = _decimal(row.get("requested_qty"))
        # Presence of an allocated PO is separate from physical receipt. Items
        # without one remain in the full MTO denominator. Catalog PO candidates
        # and free stock are not allocations to this particular material item.
        has_po = supply._truthy_flag(row.get("has_po"))
        with_po += int(has_po)
        allocated = _decimal(row.get("allocated_qty"))
        if has_po and requested is not None and requested > 0 and allocated is not None:
            if allocated >= requested:
                fully_allocated += 1
            elif allocated > 0:
                partly_allocated += 1
        if requested is None or requested <= 0:
            invalid += 1
            continue
        at_yard = supply._supply_item_is_at_yard(row)
        installed = _field_complete(docs_by_id.get(row["document_id"], {}), observed_on)
        if at_yard or installed:
            ready += 1
            received += 1
        elif (_decimal(row.get("yard_qty")) or Decimal(0)) > 0:
            received += 1
    if not total:
        status = "not_applicable" if complete_scope else "unknown"
    elif ready == total and complete_scope:
        status = "ready"
    elif received:
        status = "partial"
    elif invalid == total:
        status = "unknown"
    else:
        status = "pending"
    if not total:
        note = "No required items in the complete current MTO." if complete_scope else "Current MTO extraction is incomplete."
    else:
        note = f"{ready}/{total} material items fully received at yard or field complete."
        if received > ready:
            note += f" {received - ready} item(s) partly received."
        if not complete_scope:
            note += " Remaining drawing scope is not fully extracted."
        if invalid:
            note += f" {invalid} item(s) need quantity verification."
    return _evidence(status, observed_on, note, total_items=total, ready_items=ready,
                     received_items=received, pending_items=total-ready-invalid,
                     unknown_items=invalid, drawing_count=len(documents),
                     items_with_po=with_po, items_without_po=total-with_po,
                     fully_po_allocated_items=fully_allocated,
                     partly_po_allocated_items=partly_allocated)


def build_material_readiness(
    lines: Iterable[str], documents: list[dict[str, Any]], materials: list[dict[str, Any]],
    supports: list[dict[str, Any]], readings: list[dict[str, Any]], *, observed_on: date,
) -> dict[str, dict[str, Any]]:
    """Pure aggregation, also used to test scope and cross-line isolation."""
    docs_by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        identity = line_identity(document.get("line"))
        if identity:
            docs_by_line[identity].append(document)
    materials_by_doc: dict[Any, dict[Any, dict[str, Any]]] = defaultdict(dict)
    for row in materials:
        materials_by_doc[row["document_id"]][row["material_item_id"]] = row
    supports_by_doc: dict[Any, set[Any]] = defaultdict(set)
    for row in supports:
        # Repeated PS/SPS references are separate physical occurrences.
        supports_by_doc[row["document_id"]].add(row["id"])
    readings_by_doc = {row["document_id"]: row for row in readings}
    result = {}
    for line in dict.fromkeys(lines):
        linked = docs_by_line.get(line_identity(line), [])
        projects = {row.get("project_id") for row in linked}
        if not linked or len(projects) > 1:
            note = "No current DATAFY drawing matches this line." if not linked else "Line occurs in multiple projects; project match required."
            result[line] = {key: _evidence("unknown", observed_on, note) for key in CATEGORIES}
            continue
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for document in linked:
            for row in materials_by_doc[document["document_id"]].values():
                category = _category(row)
                if category:
                    grouped[category].append(row)
        categories = {key: _material_result(grouped[key], linked, observed_on) for key in CATEGORIES}
        support_result = categories["supports"]
        occurrence_count = sum(max(
            len(supports_by_doc[row["document_id"]]),
            int(readings_by_doc.get(row["document_id"], {}).get("supports_found") or 0),
        ) for row in linked)
        reading_complete = all(
            int(readings_by_doc.get(row["document_id"], {}).get("extractor_version") or 0) >= 2
            and (_date(readings_by_doc[row["document_id"]].get("read_at")) or date.max) <= observed_on
            and int(readings_by_doc[row["document_id"]].get("supports_found") or 0) == len(supports_by_doc[row["document_id"]])
            for row in linked
        )
        all_installed = all(_field_complete(row, observed_on) for row in linked)
        if all_installed and (occurrence_count or grouped["supports"]):
            support_result["status"] = "ready"
            support_result["note"] = "All linked drawings are confirmed field complete in DATAFY."
        elif occurrence_count:
            support_result["status"] = "partial" if support_result["counts"]["received_items"] else "pending"
            support_result["note"] += (
                f" {occurrence_count} PS/SPS support occurrences; fabrication/receipt confirmation remains outstanding."
            )
        elif not reading_complete:
            if support_result["status"] == "ready":
                support_result["status"] = "partial"
            elif support_result["status"] == "not_applicable":
                support_result["status"] = "unknown"
            support_result["note"] += " Support geometry reading is incomplete."
        support_result["counts"]["support_occurrences"] = occurrence_count
        support_result["counts"]["support_scope_complete"] = reading_complete
        result[line] = categories
    return result


def skyline_material_readiness(
    lines: Iterable[str], *, as_of_date: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Read complete current scope; no campaign/date/family/PO screen filters."""
    requested = list(dict.fromkeys(lines))
    observed_on = timezone.localdate()
    if not requested:
        return {}
    if as_of_date is not None and as_of_date < observed_on:
        return {line: {key: _evidence("unknown", as_of_date, "Live DATAFY data does not establish historical readiness.")
                       for key in CATEGORIES} for line in requested}
    cache_identity = [observed_on.isoformat(), sorted(requested),
                      settings.DATAFY_DB_HOST, settings.DATAFY_DB_PORT,
                      settings.DATAFY_DB_NAME, settings.DATAFY_DB_USER]
    cache_key = "skyline-materials:v4:" + hashlib.sha256(json.dumps(cache_identity).encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return deepcopy(cached)
    identities = {line_identity(line) for line in requested}
    with supply._datafy_conn() as conn:
        cur = conn.cursor()
        documents = [row for row in supply._rows(cur, _DOCUMENTS_SQL)
                     if line_identity(row.get("line")) in identities]
        doc_ids = [row["document_id"] for row in documents]
        materials = supply._rows(cur, fabrication._COVERAGE_ITEMS_SQL, (doc_ids, doc_ids)) if doc_ids else []
        if doc_ids:
            allocations = supply._rows(cur, _ALLOCATIONS_SQL, (doc_ids,))
            po_identity_rows = supply._rows(cur, _PO_IDENTITIES_SQL)
            allocated_po_ids = sorted({row["po_id"] for row in allocations})
            item_identity_rows = supply._rows(cur, _PO_ITEM_IDENTITIES_SQL, (allocated_po_ids,)) if allocated_po_ids else []
            enrich_material_receipts(materials, allocations, po_identity_rows, item_identity_rows)
            families = {row["material_item_id"]: row for row in supply._rows(cur, _MATERIAL_FAMILIES_SQL, (doc_ids,))}
            for row in materials:
                row.update(families.get(row["material_item_id"], {}))
            relations = supply._rows(cur, _SUPPORT_RELATIONS_SQL)[0]
            valve_tags = supply._rows(cur, _VALVE_TAGS_SQL, (doc_ids,)) if relations.get("component_tags") else []
            valve_items = {(row["document_id"], row["material_item_id"]) for row in valve_tags}
            for row in materials:
                if (row["document_id"], row["material_item_id"]) in valve_items:
                    row["component_category"] = "valve"
            supports = supply._rows(cur, _SUPPORTS_SQL, (doc_ids,)) if relations.get("supports") else []
            readings = supply._rows(cur, _READINGS_SQL, (doc_ids,)) if relations.get("readings") else []
        else:
            supports, readings = [], []
    result = build_material_readiness(requested, documents, materials, supports, readings, observed_on=observed_on)
    cache.set(cache_key, result, timeout=60)
    return result


def skyline_material_readiness_safe(lines: Iterable[str], *, as_of_date: date | None = None) -> dict:
    requested = list(lines)
    try:
        return skyline_material_readiness(requested, as_of_date=as_of_date)
    except Exception:
        logger.exception("Skyline DATAFY material readiness unavailable")
        return {line: {key: _evidence("unknown", as_of_date or timezone.localdate(),
                       "DATAFY material readiness is temporarily unavailable.")
                       for key in CATEGORIES} for line in requested}

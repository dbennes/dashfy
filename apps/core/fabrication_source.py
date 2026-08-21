"""Fabrication progress — porte da tela /fabrication/ do SPDM para a S03.

A tela original (``03 - SPDM/fabrication/views.py::fabrication_list``) usa o ORM
do proprio SPDM. Aqui o DASHBOARD le as mesmas tabelas direto no PostgreSQL do
DATAFY/SPDM (``fabrication_fabricationpackage``, ``fabrication_p6import``,
``fabrication_fabricationprogressentry``) e reimplementa a matematica que vive
nos metodos do model, para que os numeros batam 1:1 com o SPDM:

* ``p6_stage_pct`` / ``p6_stage_is_applicable`` / ``stage_weight`` / ``p6_overall_pct``
* ``_package_wbs_path`` (hierarquia WBS gravada no import do P6)
* ``_status_for`` (maquina de estados da linha)
* ``_charts_payload`` (curva S planejada x real e tonelagem por campanha)

A cobertura de PO (colunas "PO" e "At yard"), os STATUS das linhas e o subnivel
de materiais por folha tambem vem DIRETO do banco do DATAFY: um SQL proprio
sobre ``core_materialitem`` / ``catalog_allocation`` / ``catalog_stockpiece`` /
``core_purchaseorder``, enriquecido com as MESMAS funcoes do motor da S02
(``_supply_enrich_material_rows``, ``_supply_fully_at_yard_material_ids``,
``_supply_apply_po_gap_status``) — nada vem de payload embutido em HTML, e os
status sao identicos aos do DATAFY por construcao.
"""
from __future__ import annotations

import json
import re
from datetime import date as date_cls, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

# (key, rotulo curto, rotulo completo, peso de fallback) — igual a SPDM.
STAGES: list[tuple[str, str, str, int]] = [
    ("prefabrication", "PreFab", "Prefabrication", 15),
    ("fitup", "Fit-up", "Fit-up / Assembly", 15),
    ("welding", "Weld", "Welding", 30),
    ("ndt", "NDT", "Non-Destructive Testing (NDT)", 10),
    ("pwht", "PWHT", "Post-Weld Heat Treatment (PWHT)", 5),
    ("final_ndt", "Final", "Final NDT & Dimensional Check", 5),
    ("hydrotest", "Hydro", "Hydrotesting", 10),
    ("painting", "Paint", "Painting", 10),
]
STAGE_KEYS = [stage[0] for stage in STAGES]
STAGE_WEIGHTS = {key: weight for key, _short, _full, weight in STAGES}
WEEKLY_PROGRESS_META_KEY = "_weekly_progress"
WEEKLY_PROGRESS_SOURCE = "epc1_iso_weekly"
WEEKLY_PROGRESS_SCHEMA = 1

DISCIPLINE_LABELS = {
    "structural": "Structural",
    "piping": "Piping",
    "": "—",
}

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------- helpers ----
def _as_dict(value: Any) -> dict:
    """As colunas JSONB podem vir como dict (psycopg2) ou texto."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_date(value: Any) -> date_cls | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value or "")[:10]
    try:
        return date_cls.fromisoformat(text)
    except ValueError:
        return None


def _fmt_date(value: Any) -> str:
    parsed = _as_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else "—"


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


# ------------------------------------------------- matematica dos estagios ---
def stage_pct(stages: dict, key: str) -> int:
    """Legacy integer presentation retained for older consumers."""
    return int(round(float(stage_value(stages, key))))


def stage_value(stages: dict, key: str) -> Decimal:
    """Exact stage percentage shared by SPDM and this read-only dashboard."""
    data = stages.get(key)
    if not isinstance(data, dict):
        return Decimal("0")
    try:
        value = Decimal(str(data.get("pct") or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    if not value.is_finite():
        return Decimal("0")
    return max(Decimal("0"), min(Decimal("100"), value))


def stage_is_applicable(stages: dict, key: str) -> bool:
    """Um estagio existe quando o ultimo import do P6 o trouxe."""
    if key == "pwht" and _weekly_overall_value(stages) is not None:
        marker = stages.get(WEEKLY_PROGRESS_META_KEY)
        if isinstance(marker, dict) and marker.get("pwht_required") is False:
            return False
    stage = stages.get(key)
    return isinstance(stage, dict) and (bool(stage.get("acts")) or "pct" in stage)


def stage_weight(stages: dict, key: str) -> float:
    """Peso por duracao do P6, com o peso legado como fallback."""
    stage = stages.get(key) if isinstance(stages.get(key), dict) else {}
    try:
        value = float(stage.get("duration_weight") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value > 0 else float(STAGE_WEIGHTS.get(key, 0))


def _weekly_overall_value(stages: dict) -> Decimal | None:
    raw = stages.get(WEEKLY_PROGRESS_META_KEY)
    if not isinstance(raw, dict):
        return None
    if raw.get("schema") != WEEKLY_PROGRESS_SCHEMA or raw.get("source") != WEEKLY_PROGRESS_SOURCE:
        return None
    if not isinstance(raw.get("pwht_required"), bool):
        return None
    try:
        date_cls.fromisoformat(str(raw.get("report_date") or ""))
    except ValueError:
        return None
    try:
        value = Decimal(str(raw.get("overall_pct")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value < 0 or value > 100:
        return None
    return value


def _duration_overall_pct(stages: dict) -> int:
    """Historical P6 duration-weighted fallback."""
    applicable = [key for key in STAGE_KEYS if stage_is_applicable(stages, key)]
    weights = {key: stage_weight(stages, key) for key in applicable}
    denominator = sum(weights.values())
    if not denominator:
        return 0
    weighted = sum(weights[key] * stage_pct(stages, key) for key in applicable)
    return int(round(weighted / denominator))


def overall_value(stages: dict) -> Decimal:
    """Exact weekly overall, falling back to the prior P6 calculation."""
    weekly = _weekly_overall_value(stages)
    return weekly if weekly is not None else Decimal(_duration_overall_pct(stages))


def overall_pct(stages: dict) -> int:
    """Legacy integer overall retained for API compatibility."""
    return int(overall_value(stages).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------- WBS -------
def _clean_wbs_path(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    path = [str(part or "").strip() for part in value]
    path = [part for part in path if part]
    if path and path[0].casefold() == "fabrication activities":
        path.insert(0, "Onshore Construction")
    return path


def wbs_path(stages: dict, campaign: str, name: str) -> list[str]:
    metadata = stages.get("_wbs") if isinstance(stages.get("_wbs"), dict) else {}
    path = _clean_wbs_path(metadata.get("path"))
    if path:
        return path
    return _clean_wbs_path(["Fabrication Activities", campaign, name])


def p6_reference(stages: dict, p6_ref: str) -> str:
    """Prefere o WBS Summary; cai no primeiro Activity ID salvo."""
    if str(p6_ref or "").strip():
        return str(p6_ref).strip()
    for key in STAGE_KEYS:
        stage = stages.get(key)
        if not isinstance(stage, dict):
            continue
        for activity in stage.get("acts") or []:
            if isinstance(activity, dict):
                activity_id = str(activity.get("id") or "").strip()
                if activity_id:
                    return activity_id
    return ""


# --------------------------------------------------------------- status ------
def status_for(
    overall: int,
    uncovered: int | None,
    linked: bool,
    mto_total: int | None,
    yard_ready: int | None,
    sheets_ready: int | None = 0,
) -> tuple[str, str]:
    """Mesma maquina de estados do SPDM (``_status_for``)."""
    if overall >= 100:
        return "shipped", "Shipped"
    if overall > 0:
        return "fabricating", "In fab"
    if not linked:
        return "unlinked", "No link"
    if uncovered is None:
        return "loading", "…"
    if (mto_total or 0) == 0:
        return "nomto", "No MTO"
    if (yard_ready or 0) >= (mto_total or 0):
        return "ready", "Ready"
    if (sheets_ready or 0) > 0:
        return "canstart", "Can start"
    if uncovered > 0:
        return "blocked", "Missing PO"
    return "delivering", "Awaiting delivery"


def _parse_coverage_date(value: Any) -> date_cls | None:
    """Mesma normalizacao de datas do SPDM: ISO, m/d/Y ou d/m/Y."""
    text = str(value or "").split(" · ", 1)[0].strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _material_arrival_risk(plan_start: date_cls | None, arrival_value: Any) -> tuple[bool, str]:
    """Alerta quando a ultima chegada ocorre ate 10 dias antes do inicio, ou depois."""
    arrival = _parse_coverage_date(arrival_value)
    if not plan_start or not arrival:
        return False, ""
    margin = (plan_start - arrival).days
    if margin > 10:
        return False, ""
    if margin < 0:
        timing = f"{abs(margin)} day(s) after the planned fabrication start"
    elif margin == 0:
        timing = "on the planned fabrication start"
    else:
        timing = f"only {margin} day(s) before the planned fabrication start"
    return True, (
        f"Material arrival risk: latest PO arrival {_fmt_date(arrival)} is {timing} "
        f"({_fmt_date(plan_start)})."
    )


# ------------------------------------------------------- curva planejada -----
def _month_key(value: date_cls) -> str:
    return value.strftime("%Y-%m")


def _month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{_MONTH_NAMES[int(month) - 1]}/{year[2:]}"


def _next_month(value: date_cls) -> date_cls:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return date_cls(year, month, 1)


def _add_time_phased_tons(
    target: dict[str, Decimal], start: date_cls, finish: date_cls, tons: Decimal
) -> None:
    """Rateia a tonelagem linearmente pelos meses cobertos pelas datas do P6."""
    if finish < start:
        finish = start
    total_days = Decimal((finish - start).days + 1)
    cursor = date_cls(start.year, start.month, 1)
    while cursor <= finish:
        following = _next_month(cursor)
        slice_start = max(start, cursor)
        slice_finish = min(finish, following - timedelta(days=1))
        days = Decimal((slice_finish - slice_start).days + 1)
        key = _month_key(cursor)
        target[key] = target.get(key, Decimal("0")) + tons * days / total_days
        cursor = following


def _planned_points(stages: dict, plan_start, plan_finish, weight: Decimal) -> dict[str, Decimal]:
    scheduled: list[tuple[Decimal, list[tuple[date_cls, date_cls, int]]]] = []
    for key, fallback_weight in STAGE_WEIGHTS.items():
        data = stages.get(key) if isinstance(stages.get(key), dict) else {}
        try:
            weight_stage = Decimal(str(data.get("duration_weight") or fallback_weight))
        except (InvalidOperation, TypeError, ValueError):
            weight_stage = Decimal(fallback_weight)
        acts = []
        for act in data.get("acts") or []:
            if not isinstance(act, dict):
                continue
            start = _as_date(act.get("start"))
            finish = _as_date(act.get("finish"))
            start = start or finish
            finish = finish or start
            if not start or not finish:
                continue
            if finish < start:
                finish = start
            acts.append((start, finish, (finish - start).days + 1))
        if acts and weight_stage > 0:
            scheduled.append((weight_stage, acts))

    out: dict[str, Decimal] = {}
    present_weight = sum((weight_stage for weight_stage, _acts in scheduled), Decimal("0"))
    if not present_weight:
        fallback = _as_date(plan_finish) or _as_date(plan_start)
        if fallback:
            out[_month_key(fallback)] = weight
        return out

    for weight_stage, acts in scheduled:
        stage_tons = weight * weight_stage / present_weight
        duration_total = sum(duration for _start, _finish, duration in acts)
        for start, finish, duration in acts:
            act_tons = stage_tons * Decimal(duration) / Decimal(duration_total)
            _add_time_phased_tons(out, start, finish, act_tons)
    return out


# ------------------------------------------------------------- leitura -------
_PACKAGE_SQL = """
select p.id, p.code, p.name, p.campaign, p.discipline, p.drawing_number, p.dwg_key,
       p.document_id, p.p6_ref, p.travel_pack_no, p.weight_tons,
       p.plan_start, p.plan_finish, p.actual_start, p.actual_finish,
       p.stages, p.sort_order,
       d.drawing_number as doc_drawing_number, d.title as doc_title,
       d.revision as doc_revision, d.priority as doc_priority
  from fabrication_fabricationpackage p
  left join core_document d on d.id = p.document_id
 where p.is_active = true
 order by p.sort_order, p.id
"""

_PROGRESS_SQL = """
select e.progress_date, sum(e.tons_delta) as total
  from fabrication_fabricationprogressentry e
  join fabrication_fabricationpackage p on p.id = e.package_id
 where p.is_active = true
 group by e.progress_date
 order by e.progress_date
"""

_IMPORT_SQL = """
select original_filename, imported_at, packages_total, packages_linked, activities_total
  from fabrication_p6import
 order by imported_at desc
 limit 1
"""

# O cursor de compatibilidade troca "?" por "%s" e escapa "%", entao o
# placeholder aqui precisa ser "?" (nao "%s").
_DOC_WEIGHT_SQL = """
select t.document_id, sum(i.calculated_weight) as total_kg
  from core_materialitem i
  join core_extractedtable t on t.id = i.table_id
 where t.document_id = any(?)
 group by t.document_id
"""

# Itens de material dos documentos linkados, com alocacao, estoque e escopo —
# a MESMA semantica do CTE do motor DATAFY da S02 (real_sources), reduzida aos
# campos que a tela de fabricacao precisa.
_COVERAGE_ITEMS_SQL = """
with match_one as (
    select material_item_id, min(catalog_item_id) as catalog_item_id
    from catalog_catalogmatch
    where material_item_id is not null
    group by material_item_id
),
alloc as (
    select a.material_item_id, sum(a.qty_allocated) as allocated_qty
    from catalog_allocation a
    group by a.material_item_id
),
stock as (
    select sp.catalog_item_id,
           sum(sp.remaining_qty) as stock_free_qty,
           string_agg(distinct nullif(po.po_number, ''), ', ') as stock_po_numbers
    from catalog_stockpiece sp
    left join core_purchaseorderitem poi on poi.id = sp.po_item_id
    left join core_purchaseorder po on po.id = poi.purchase_order_id
    group by sp.catalog_item_id
),
doc_tables as (
    select d.id as document_id,
           max(case
             when (upper(coalesce(t.name, '')) like '%FABRICATION%'
                   or upper(coalesce(t.name, '')) like '%FABRICAC%')
              and not (upper(coalesce(t.name, '')) like '%DEMOLISH%'
                       or upper(coalesce(t.name, '')) like '%DEMOLI%'
                       or upper(coalesce(t.name, '')) like '%REMOV%')
             then 1 else 0 end) as has_explicit_fab
    from core_document d
    left join core_extractedtable t on t.document_id = d.id
    where d.id = any(?)
    group by d.id
)
select mi.id as material_item_id,
       d.id as document_id,
       t.id as table_id,
       t.name as table_name,
       t.page_number,
       t."order" as table_order,
       mi.row_order,
       mi.item_number,
       mi.material_code,
       mi.extra_fields,
       mi.description,
       mi.unit,
       coalesce(mi.quantity, 0) as requested_qty,
       coalesce(alloc.allocated_qty, 0) as allocated_qty,
       greatest(coalesce(mi.quantity, 0) - coalesce(alloc.allocated_qty, 0), 0) as missing_qty,
       case when ci.id is null then 1 else 0 end as stock_free_na,
       case when ci.id is null then null else coalesce(stock.stock_free_qty, 0) end as stock_free_qty,
       coalesce(nullif(stock.stock_po_numbers, ''), '') as stock_po_numbers,
       case
         when upper(coalesce(t.name, '')) like '%DEMOLISH%'
           or upper(coalesce(t.name, '')) like '%DEMOLI%'
           or upper(coalesce(t.name, '')) like '%REMOV%'
         then 'other'
         when upper(coalesce(t.name, '')) like '%ERECTION%'
           or upper(coalesce(t.name, '')) like '%INSTALLATION%'
           or upper(coalesce(t.name, '')) like '%ONBOARD%'
         then 'erection'
         when upper(coalesce(t.name, '')) like '%FABRICATION%'
           or upper(coalesce(t.name, '')) like '%FABRICAC%'
         then 'fabrication'
         when coalesce(dt.has_explicit_fab, 0) = 0
         then 'fabrication'
         else 'other'
       end as scope
from core_document d
join core_extractedtable t on t.document_id = d.id
join core_materialitem mi on mi.table_id = t.id
left join match_one cm on cm.material_item_id = mi.id
left join catalog_catalogitem ci on ci.id = cm.catalog_item_id
left join alloc on alloc.material_item_id = mi.id
left join stock on stock.catalog_item_id = ci.id
left join doc_tables dt on dt.document_id = d.id
where d.id = any(?)
order by d.id, t.page_number, t."order", mi.row_order
"""

# Alocacoes -> PO (com o payload do procurement plan) dos mesmos documentos,
# para chegada no patio e data prevista — identico ao motor da S02.
_COVERAGE_PO_SQL = """
select a.material_item_id,
       a.id as allocation_id,
       a.qty_allocated,
       po.id as po_id,
       po.po_number,
       po.original_filename as po_original_filename,
       po.expected_date as po_expected_text,
       po.procurement_plan_stage,
       po.procurement_plan_kind,
       po.procurement_plan_date,
       po.procurement_plan_payload
from catalog_allocation a
join core_materialitem mi on mi.id = a.material_item_id
join core_extractedtable t on t.id = mi.table_id
join catalog_stockpiece sp on sp.id = a.stock_piece_id
join core_purchaseorderitem poi on poi.id = sp.po_item_id
join core_purchaseorder po on po.id = poi.purchase_order_id
where t.document_id = any(?)
"""

_SPOOL_PLAN_SQL = """
select id, document_id, table_key, column_count, source_codes
  from fabrication_fabricationspoolplan
 where document_id = any(?)
"""

_SPOOL_CELL_SQL = """
select plan_id, item_key, spool_index, quantity
  from fabrication_fabricationspoolcell
 where plan_id = any(?)
"""


def _fetch_coverage_items(cur, doc_ids: list[int]) -> list[dict]:
    """Le e enriquece os itens de material direto do banco do DATAFY."""
    from . import real_sources as rs

    if not doc_ids:
        return []
    items = rs._rows(cur, _COVERAGE_ITEMS_SQL, (doc_ids, doc_ids))
    po_rows = rs._rows(cur, _COVERAGE_PO_SQL, (doc_ids,))

    yard_ids = rs._supply_fully_at_yard_material_ids(items, po_rows)
    po_ids = {row["material_item_id"] for row in po_rows}

    yard_qty = rs._supply_yard_allocation_qty_by_material(po_rows)
    po_names: dict[Any, list[str]] = {}
    po_entries: dict[Any, list[dict]] = {}
    expected: dict[Any, str] = {}
    expected_texts: dict[Any, list[str]] = {}
    yard_dates: dict[Any, str] = {}
    plan_entries: dict[Any, list[tuple[str, str, str]]] = {}
    for row in po_rows:
        material_id = row.get("material_item_id")
        number = str(row.get("po_number") or row.get("po_original_filename") or "").strip()
        expected_text = str(row.get("po_expected_text") or "").strip()
        if number and number not in po_names.setdefault(material_id, []):
            po_names[material_id].append(number)
        # POs individuais do item (mesma dedup do _po_entries do SPDM)
        if number:
            entry_key_list = po_entries.setdefault(material_id, [])
            if not any(e["number"] == number and e["expected"] == expected_text for e in entry_key_list):
                entry_key_list.append({"number": number, "expected": expected_text})
        if expected_text and expected_text not in expected_texts.setdefault(material_id, []):
            expected_texts[material_id].append(expected_text)
        delivery = rs._po_delivery_date_iso(row)
        if delivery and delivery > expected.get(material_id, ""):
            expected[material_id] = delivery
        if rs._po_row_has_yard_actual(row) and delivery and delivery > yard_dates.get(material_id, ""):
            yard_dates[material_id] = delivery
        # procurement plan (mesma logica do _item_plan_info do SPDM)
        plan_date = str(row.get("procurement_plan_date") or "").strip()
        if plan_date:
            entry = (
                plan_date,
                str(row.get("procurement_plan_stage") or "").strip(),
                str(row.get("procurement_plan_kind") or "").strip(),
            )
            if entry not in plan_entries.setdefault(material_id, []):
                plan_entries[material_id].append(entry)

    for row in items:
        material_id = row["material_item_id"]
        names = po_names.get(material_id) or []
        if names:
            row["po_covering"] = ", ".join(names)
        # rotulo de PO no formato do SPDM: ate 2 numeros + " +n"
        row["po_label"] = (
            ", ".join(names[:2]) + (f" +{len(names) - 2}" if len(names) > 2 else "")
        ) if names else ""
        row["po_entries"] = po_entries.get(material_id) or []
        # "expected" no formato do _po_labels do SPDM: datas texto das POs
        row["po_expected_text"] = " · ".join((expected_texts.get(material_id) or [])[:2])
        row["po_expected_date"] = expected.get(material_id, "")
        row["yard_date"] = yard_dates.get(material_id, "")
        row["yard_qty"] = float(yard_qty.get(material_id) or 0)
        entries = plan_entries.get(material_id) or []
        if entries:
            plan_date, plan_stage, plan_kind = entries[0]
            label = plan_date + (" A" if plan_kind.lower() == "actual" else "")
            if len(entries) > 1:
                label += f" +{len(entries) - 1}"
            row["plan"] = label
            row["plan_tooltip"] = " · ".join(filter(None, [plan_stage, plan_kind, plan_date]))
        else:
            row["plan"] = ""
            row["plan_tooltip"] = ""

    # Mesmo enriquecimento do motor da S02: status ok/partial/missing/unknown,
    # escopo normalizado, has_po, yard_actual e motivo do gap de PO.
    rs._supply_enrich_material_rows(items, yard_ids, po_ids)
    return items


# ------------------------------------------------ spools (read-only) ---------
# Replica fiel das chaves/colunas de spool do SPDM (fabrication/views.py),
# somente leitura: o dashboard nunca cria plano nem grava celula.
_SPOOL_KEY_SPACE_RX = re.compile(r"\s+")
_SPOOL_SUFFIX_RX = re.compile(r"-(\d{1,3})$")


def _spool_key_text(value: Any) -> str:
    return _SPOOL_KEY_SPACE_RX.sub(" ", str(value or "").strip().upper()).replace("|", "/")


def _spool_table_key(page_number: Any, table_order: Any, name: Any) -> str:
    return "|".join([
        f"PAGE:{int(page_number or 0)}",
        f"ORDER:{int(table_order or 0)}",
        f"NAME:{_spool_key_text(name)}",
    ])[:255]


def _spool_item_base_key(row: dict) -> str:
    item_number = _spool_key_text(row.get("item_number"))
    material_code = _spool_key_text(row.get("material_code"))
    if item_number:
        return f"ITEM:{item_number}|MATERIAL:{material_code}"
    if material_code:
        return f"MATERIAL:{material_code}"
    return f"ROW:{int(row.get('row_order') or 0)}"


def _spool_item_keys(rows: list[dict]) -> list[str]:
    bases = [_spool_item_base_key(row) for row in rows]
    counts: dict[str, int] = {}
    for base in bases:
        counts[base] = counts.get(base, 0) + 1
    out: list[str] = []
    for row, base in zip(rows, bases):
        key = base
        if counts[base] > 1:
            key = f"{base}|ROW:{int(row.get('row_order') or 0)}"
        out.append(key[:255])
    return out


def _spool_detected_codes(rows: list[dict]) -> list[str]:
    """Codigos de spool detectados na extracao (mesma regra do _table_spool_info)."""
    codes: set[str] = set()
    for row in rows:
        extra = _as_dict(row.get("extra_fields"))
        raw_candidates = extra.get("spool_candidates")
        if isinstance(raw_candidates, (list, tuple)):
            for raw_code in raw_candidates:
                code = str(raw_code or "").strip().upper()
                if code and code != "TBD":
                    codes.add(code)
        raw_code = str(
            extra.get("spool_code") or extra.get("SPOOL") or extra.get("Spool") or ""
        ).strip().upper()
        if raw_code and raw_code != "TBD":
            codes.add(raw_code)

    def sort_key(code: str) -> tuple[int, int, str]:
        match = _SPOOL_SUFFIX_RX.search(code)
        if match:
            return 0, int(match.group(1)), code
        return 1, 0, code

    return sorted(codes, key=sort_key)


def _spool_decimal_text(value: Decimal) -> str:
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"


def _spool_columns_payload(column_count: int, source_codes: list[str]) -> list[dict]:
    return [
        {
            "index": index,
            "label": f"SPOOL-{index:02d}",
            "source_code": str(source_codes[index - 1] or "").strip()
            if index <= len(source_codes)
            else "",
        }
        for index in range(1, max(int(column_count or 1), 1) + 1)
    ]


def _spool_item_payload_ro(
    row: dict,
    item_key: str,
    column_count: int,
    quantities: dict[tuple[str, int], Decimal],
) -> dict:
    """Mesmo payload do _spool_item_payload do SPDM, com can_edit sempre False."""
    total = row.get("requested_qty")
    error = ""
    try:
        total_dec = Decimal(str(total)) if total is not None else None
    except (InvalidOperation, TypeError, ValueError):
        total_dec = None
    if total_dec is None:
        error = "Material quantity is missing."
    elif not total_dec.is_finite() or total_dec < 0:
        error = "Material quantity is invalid."

    values: dict[str, str] = {}
    assigned = Decimal("0")
    for index in range(2, int(column_count or 1) + 1):
        stored = quantities.get((item_key, index))
        value = stored if stored is not None else Decimal("0")
        assigned += value
        values[str(index)] = _spool_decimal_text(value) if stored is not None else ""

    residual = (total_dec - assigned) if total_dec is not None and total_dec.is_finite() else Decimal("0")
    if total_dec is not None and total_dec.is_finite() and residual < 0:
        error = "Spool quantities exceed the material quantity."
    values = {"1": _spool_decimal_text(residual), **values}
    return {
        "qty_raw": _spool_decimal_text(total_dec) if total_dec is not None and total_dec.is_finite() else "",
        "spool_values": values,
        "spool_residual": values["1"],
        "spool_error": error,
        "can_edit": False,
    }


def _fetch_spool_maps(cur, doc_ids: list[int]) -> tuple[dict, dict]:
    """Planos de spool por (document_id, table_key) e celulas por plano."""
    from . import real_sources as rs

    if not doc_ids:
        return {}, {}
    plans = rs._rows(cur, _SPOOL_PLAN_SQL, (doc_ids,))
    plan_by_key = {
        (int(plan["document_id"]), str(plan["table_key"])): plan
        for plan in plans
    }
    plan_ids = [int(plan["id"]) for plan in plans]
    cells: dict[int, dict[tuple[str, int], Decimal]] = {}
    if plan_ids:
        for cell in rs._rows(cur, _SPOOL_CELL_SQL, (plan_ids,)):
            cells.setdefault(int(cell["plan_id"]), {})[
                (str(cell["item_key"]), int(cell["spool_index"]))
            ] = _decimal(cell.get("quantity"))
    return plan_by_key, cells


def _coverage_index(material_rows: list[dict] | None) -> dict[int, dict]:
    """Cobertura por documento (escopo fabricacao) a partir dos itens da S02.

    Mesmo criterio da tela do SPDM: covered = item totalmente alocado
    (status "ok" no motor DATAFY), yard = chegada confirmada no patio,
    sheets_ready = folhas de fabricacao 100% no patio (libera "Can start").
    """
    index: dict[int, dict] = {}
    sheets: dict[int, dict[Any, list[int]]] = {}
    for row in material_rows or []:
        document_id = row.get("document_id")
        if not document_id:
            continue
        if str(row.get("scope") or "") != "fabrication":
            continue
        document_id = int(document_id)
        bucket = index.setdefault(
            document_id,
            {"total": 0, "covered": 0, "yard": 0, "arrival": "", "sheets_total": 0, "sheets_ready": 0},
        )
        bucket["total"] += 1
        if str(row.get("status") or "") == "ok":
            bucket["covered"] += 1
        at_yard = int(row.get("yard_actual") or 0)
        if at_yard:
            bucket["yard"] += 1
        table_stats = sheets.setdefault(document_id, {}).setdefault(
            row.get("table_id") or f"{row.get('table_name')}|{row.get('page_number')}",
            [0, 0],
        )
        table_stats[0] += 1
        table_stats[1] += 1 if at_yard else 0
        arrival = str(row.get("po_expected_date") or "")
        if arrival and arrival > bucket["arrival"]:
            bucket["arrival"] = arrival
    for document_id, bucket in index.items():
        bucket["uncovered"] = max(bucket["total"] - bucket["covered"], 0)
        bucket["pct"] = int(round(100 * bucket["covered"] / bucket["total"])) if bucket["total"] else 0
        table_map = sheets.get(document_id) or {}
        bucket["sheets_total"] = len(table_map)
        bucket["sheets_ready"] = sum(
            1 for total, yard in table_map.values() if total > 0 and yard >= total
        )
    return index


# Chip de motivo do subnivel — mesmas classes E rotulos da tela do SPDM
# (_item_status/_pending_reason em fabrication/views.py).
def _detail_item_status(row: dict) -> tuple[str, str]:
    status = str(row.get("status") or "")
    if status == "ok":
        return "covered", "Covered"
    if status == "partial":
        return "po_insuficiente", "Insufficient PO"
    if status == "unknown":
        return "revisao", "Review"
    gap = str(row.get("po_gap_status") or "")
    if gap == "no_balance":
        return "po_consumida", "PO balance used"
    if gap == "not_allocated":
        return "a_alocar", "Awaiting allocation"
    return "sem_po", "No PO"


def _fmt_qty(value: Any) -> str:
    dec = _decimal(value)
    text = f"{dec:,.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _detail_docs(
    material_rows: list[dict] | None,
    doc_ids: set[int],
    spool_plans: dict | None = None,
    spool_cells: dict | None = None,
) -> dict[str, list[dict]]:
    """Subnivel do desenho: materiais agrupados por tabela extraida (folha).

    Mesmo shape do JSON do ``fabrication_detail`` do SPDM: todas as tabelas do
    documento, com chip de escopo, released, stats de PO/patio, colunas de
    spool (somente leitura) e itens com status/PO/at yard/proc. plan.
    """
    spool_plans = spool_plans or {}
    spool_cells = spool_cells or {}
    docs: dict[str, dict] = {}
    raw_rows: dict[tuple[str, str], list[dict]] = {}
    for row in material_rows or []:
        document_id = row.get("document_id")
        if not document_id or int(document_id) not in doc_ids:
            continue
        scope = str(row.get("scope") or "other")
        # Somente as folhas de FABRICACAO no subnivel — sem erection/other.
        if scope != "fabrication":
            continue
        doc_key = str(int(document_id))
        doc = docs.setdefault(doc_key, {})
        table_key = str(row.get("table_id") or f"{row.get('table_name')}|{row.get('page_number')}")
        raw_rows.setdefault((doc_key, table_key), []).append(row)
        table = doc.setdefault(table_key, {
            "table_id": row.get("table_id") or 0,
            "name": str(row.get("table_name") or "Table"),
            "page": row.get("page_number") or "",
            "table_order": row.get("table_order") or 0,
            "scope": scope,
            "scope_label": str(row.get("scope_label") or scope.title()),
            "in_fabrication": scope == "fabrication",
            "total": 0,
            "covered": 0,
            "yard": 0,
            "can_edit_spools": False,
            "items": [],
        })
        chip, chip_label = _detail_item_status(row)
        requested = _decimal(row.get("requested_qty"))
        yard_qty = _decimal(row.get("yard_qty"))
        if int(row.get("yard_actual") or 0):
            yard_state = "ready"
        elif yard_qty > 0:
            yard_state = "partial"
        elif int(row.get("has_po") or 0):
            yard_state = "waiting"
        else:
            yard_state = ""
        table["total"] += 1
        if chip == "covered":
            table["covered"] += 1
        if yard_state == "ready":
            table["yard"] += 1
        table["items"].append({
            "item_id": row.get("material_item_id"),
            "item": str(row.get("item_number") or ""),
            "material": str(row.get("description") or "—"),
            "qty": _fmt_qty(requested),
            "unit": str(row.get("unit") or "").strip(),
            "status": chip,
            "status_label": chip_label,
            "po": str(row.get("po_label") or ""),
            "yard": yard_state,
            "yard_date": str(row.get("yard_date") or ""),
            "expected": str(row.get("po_expected_date") or ""),
            "plan": str(row.get("plan") or ""),
            "plan_tooltip": str(row.get("plan_tooltip") or ""),
        })

    out: dict[str, list[dict]] = {}
    for doc_key, tables in docs.items():
        ordered = sorted(tables.values(), key=lambda t: (str(t["page"]), t["name"]))
        for table in ordered:
            total = table["total"]
            table["pct"] = int(round(100 * table["covered"] / total)) if total else 0
            table["yard_pct"] = int(round(100 * table["yard"] / total)) if total else 0
            table["yard_released"] = bool(total) and table["yard"] >= total

            # ---- colunas de spool (mesma resolucao do SPDM, read-only) ----
            table_key = str(table["table_id"] or f"{table['name']}|{table['page']}")
            rows_for_table = raw_rows.get((doc_key, table_key)) or []
            detected = _spool_detected_codes(rows_for_table)
            minimum = max(len(detected), 1)
            plan = spool_plans.get((
                int(doc_key),
                _spool_table_key(table["page"], table["table_order"], table["name"]),
            ))
            if plan:
                column_count = max(int(plan.get("column_count") or 1), minimum)
                source_codes = plan.get("source_codes")
                source_codes = [str(v or "").strip() for v in source_codes] if isinstance(source_codes, list) else []
                source_codes = source_codes[:column_count]
                source_codes.extend([""] * (column_count - len(source_codes)))
                for idx, code in enumerate(detected):
                    if idx < len(source_codes):
                        source_codes[idx] = code
                quantities = spool_cells.get(int(plan.get("id") or 0)) or {}
            else:
                column_count = minimum
                source_codes = detected + [""] * (minimum - len(detected))
                quantities = {}
            table["spool_columns"] = _spool_columns_payload(column_count, source_codes)
            item_keys = _spool_item_keys(rows_for_table)
            for item, row, item_key in zip(table["items"], rows_for_table, item_keys):
                item.update(_spool_item_payload_ro(row, item_key, column_count, quantities))
            table.pop("table_order", None)
        out[doc_key] = ordered
    return out




def _pend_tooltip(nums: dict) -> str:
    bits = [f"{nums['covered']}/{nums['total']} fabrication items covered"]
    if nums["uncovered"]:
        bits.append(f"{nums['uncovered']} missing PO")
    if nums["total"]:
        bits.append(f"{nums['yard']}/{nums['total']} at yard")
    if nums.get("sheets_total"):
        bits.append(f"{nums.get('sheets_ready', 0)}/{nums['sheets_total']} sheet(s) released")
    if nums.get("arrival"):
        bits.append(f"arrival {nums['arrival']}")
    return " · ".join(bits)


def _wbs_tree_entries(rows: list[dict]) -> list[dict]:
    """Achata a ancestralidade do Primavera em linhas navegaveis da tabela."""
    entries: list[dict] = []
    emitted: set[str] = set()
    for row in rows:
        path = list(row.get("wbs_path") or [])
        for index, node_name in enumerate(path[:-1]):
            node_path = path[: index + 1]
            path_key = " › ".join(node_path)
            if path_key in emitted:
                continue
            emitted.add(path_key)
            entries.append({
                "kind": "wbs",
                "name": node_name,
                "level": index + 1,
                "depth": index,
                "path_key": path_key,
                "parent_key": " › ".join(node_path[:-1]),
            })
        entries.append({"kind": "package", "row": row})
    return entries


def _charts_payload(rows: list[dict], actual_by_month: dict[str, Decimal]) -> dict:
    planned_by_month: dict[str, Decimal] = {}
    campaign_planned: dict[str, Decimal] = {}
    campaign_done: dict[str, Decimal] = {}

    for row in rows:
        weight = row["_weight"]
        if weight <= 0:
            continue
        camp = (row["campaign"] or "No campaign").split("(")[0].strip()
        campaign_planned[camp] = campaign_planned.get(camp, Decimal("0")) + weight
        campaign_done[camp] = campaign_done.get(camp, Decimal("0")) + (
            weight * Decimal(row["overall"]) / Decimal("100")
        )
        for key, value in row["_planned_points"].items():
            planned_by_month[key] = planned_by_month.get(key, Decimal("0")) + value

    months = sorted(set(planned_by_month) | set(actual_by_month))
    curve_basis = sum(planned_by_month.values(), Decimal("0"))
    current_month = _month_key(date_cls.today())
    planned_cum: list[float] = []
    actual_cum: list[float | None] = []
    run_planned = run_actual = Decimal("0")
    for key in months:
        run_planned += planned_by_month.get(key, Decimal("0"))
        run_actual += actual_by_month.get(key, Decimal("0"))
        planned_cum.append(
            round(float(run_planned * Decimal("100") / curve_basis), 1) if curve_basis else 0
        )
        # A linha do real para no mes corrente — nao desenha futuro.
        actual_cum.append(
            round(float(run_actual * Decimal("100") / curve_basis), 1)
            if (curve_basis and key <= current_month)
            else None
        )

    return {
        "curve": {
            "labels": [_month_label(key) for key in months],
            "planned": planned_cum,
            "actual": actual_cum,
            "unit": "percent",
        },
        "campaign": {
            "labels": list(campaign_planned.keys()),
            "planned": [round(float(value), 1) for value in campaign_planned.values()],
            "done": [round(float(value), 1) for value in campaign_done.values()],
        },
    }


def fabrication_progress() -> dict:
    """Payload da S03: KPIs, arvore WBS + linhas, graficos e import P6.

    Tudo lido direto do PostgreSQL do DATAFY/SPDM — pacotes, progresso datado
    e cobertura de PO por item — sem depender de payload de outra secao.
    """
    from .real_sources import _datafy_conn, _rows

    with _datafy_conn() as conn:
        cur = conn.cursor()
        packages = _rows(cur, _PACKAGE_SQL)
        progress_rows = _rows(cur, _PROGRESS_SQL)
        import_rows = _rows(cur, _IMPORT_SQL)
        doc_ids = [int(p["document_id"]) for p in packages if p.get("document_id")]
        weight_rows = _rows(cur, _DOC_WEIGHT_SQL, (doc_ids,)) if doc_ids else []
        coverage_items = _fetch_coverage_items(cur, doc_ids)

    cov_index = _coverage_index(coverage_items)

    kg_by_doc = {
        int(row["document_id"]): _decimal(row["total_kg"])
        for row in weight_rows
        if row.get("document_id")
    }

    rows: list[dict] = []
    for package in packages:
        stages = _as_dict(package.get("stages"))
        document_id = package.get("document_id")
        linked = document_id is not None
        overall = float(overall_value(stages))

        stage_cells = []
        stages_for_json: dict[str, int | None] = {}
        for key in STAGE_KEYS:
            applicable = stage_is_applicable(stages, key)
            pct = float(stage_value(stages, key)) if applicable else None
            stage_cells.append({"key": key, "applicable": applicable, "pct": pct})
            stages_for_json[key] = pct

        empty_nums = {
            "total": 0, "covered": 0, "uncovered": 0, "yard": 0, "pct": 0,
            "arrival": "", "sheets_total": 0, "sheets_ready": 0,
        }
        nums = (cov_index.get(int(document_id)) or empty_nums) if linked else empty_nums

        plan_start = _as_date(package.get("plan_start"))
        status_key, status_label = status_for(
            overall, nums["uncovered"], linked, nums["total"], nums["yard"],
            nums.get("sheets_ready") or 0,
        )
        start_risk, start_risk_title = _material_arrival_risk(plan_start, nums["arrival"])

        path = wbs_path(stages, package.get("campaign") or "", package.get("name") or "")
        drawing = (
            package.get("doc_drawing_number")
            or package.get("drawing_number")
            or package.get("dwg_key")
            or "—"
        )
        title = package.get("doc_title") or package.get("name") or ""
        priority = package.get("doc_priority")
        if priority is not None and int(priority) == 999:
            priority = None
        discipline = str(package.get("discipline") or "")

        weight_tons = _decimal(package.get("weight_tons"))
        if weight_tons <= 0 and linked:
            kg = kg_by_doc.get(int(document_id)) or Decimal("0")
            weight_tons = (kg / Decimal("1000")).quantize(Decimal("0.001")) if kg else Decimal("0")

        rows.append({
            "pk": package["id"],
            "code": package.get("code") or "",
            "p6_ref": p6_reference(stages, package.get("p6_ref") or ""),
            "travel_pack_no": package.get("travel_pack_no") or "",
            "dwg": drawing,
            "rev": package.get("doc_revision") or "",
            "title": title,
            "name": package.get("name") or "",
            "discipline": discipline,
            "discipline_label": DISCIPLINE_LABELS.get(discipline, discipline.title() or "—"),
            "campaign": package.get("campaign") or "",
            "wbs_path": path,
            "wbs_level": len(path),
            "wbs_key": " › ".join(path),
            "wbs_parent_key": " › ".join(path[:-1]),
            "priority": priority,
            "weight_tons": weight_tons,
            "start_plan": _fmt_date(package.get("plan_start")),
            "start_plan_iso": plan_start.isoformat() if plan_start else "",
            "finish_plan": _fmt_date(package.get("plan_finish")),
            "start_act": _fmt_date(package.get("actual_start")),
            "finish_act": _fmt_date(package.get("actual_finish")),
            "linked": linked,
            "doc_id": document_id,
            "pend_count": nums["uncovered"] if linked else 0,
            "mto_total": nums["total"] if linked else 0,
            "yard_ready": nums["yard"] if linked else 0,
            "sheets_ready": nums.get("sheets_ready") or 0,
            "cov_covered": nums["covered"],
            "cov_pct": nums["pct"],
            "arrival": nums["arrival"],
            "start_risk": start_risk,
            "start_risk_title": start_risk_title,
            "pend_title": _pend_tooltip(nums) if linked else "",
            "stage_cells": stage_cells,
            "stages_json": json.dumps(stages_for_json),
            "overall": overall,
            "status_key": status_key,
            "status_label": status_label,
            "search": " ".join(filter(None, [
                package.get("code"), drawing, title, package.get("name"),
                package.get("campaign"), package.get("travel_pack_no"), discipline,
                p6_reference(stages, package.get("p6_ref") or ""), *path,
            ])).lower(),
            "_weight": weight_tons,
            "_planned_points": _planned_points(
                stages, package.get("plan_start"), package.get("plan_finish"), weight_tons
            ),
        })

    actual_by_month: dict[str, Decimal] = {}
    for row in progress_rows:
        progress_date = _as_date(row.get("progress_date"))
        if not progress_date:
            continue
        key = _month_key(progress_date)
        actual_by_month[key] = actual_by_month.get(key, Decimal("0")) + _decimal(row.get("total"))

    total = len(rows)
    ready = sum(1 for row in rows if row["status_key"] == "ready")
    pending = sum(1 for row in rows if row["pend_count"])
    linked_count = sum(1 for row in rows if row["linked"])
    avg = round(sum(row["overall"] for row in rows) / total, 2) if total else 0

    charts = _charts_payload(rows, actual_by_month)
    last_import = import_rows[0] if import_rows else None

    for row in rows:
        row.pop("_planned_points", None)

    return {
        "available": True,
        "stages": STAGES,
        "stages_json": json.dumps(STAGES),
        "rows": rows,
        "tree": _wbs_tree_entries(rows),
        "rows_total": total,
        "kpis": {
            "total": total,
            "ready": ready,
            "pending": pending,
            "avg": avg,
            "linked": linked_count,
        },
        "last_import": last_import,
        "charts": charts,
        "charts_json": json.dumps(charts, default=str),
    }


def fabrication_progress_safe() -> dict:
    """Nunca derruba o cockpit: em falha devolve payload vazio com o erro."""
    try:
        return fabrication_progress()
    except Exception as exc:  # pragma: no cover - depende do Postgres externo
        empty_charts = {
            "curve": {"labels": [], "planned": [], "actual": [], "unit": "percent"},
            "campaign": {"labels": [], "planned": [], "done": []},
        }
        return {
            "available": False,
            "error": str(exc),
            "stages": STAGES,
            "stages_json": json.dumps(STAGES),
            "rows": [],
            "tree": [],
            "rows_total": 0,
            "kpis": {"total": 0, "ready": 0, "pending": 0, "avg": 0, "linked": 0},
            "last_import": None,
            "charts": empty_charts,
            "charts_json": json.dumps(empty_charts),
        }


_PACKAGE_ONE_SQL = """
select p.id, p.code, p.name, p.document_id, p.p6_ref, p.stages, p.plan_start,
       p.drawing_number, p.dwg_key,
       d.drawing_number as doc_drawing_number, d.title as doc_title
  from fabrication_fabricationpackage p
  left join core_document d on d.id = p.document_id
 where p.id = ?
"""


def fabrication_package_detail(pk: int) -> dict:
    """Subnivel de um desenho, lido na hora do clique direto do banco DATAFY:
    materiais por folha extraida com PO, patio, previsao, motivo e colunas de
    spool — o mesmo JSON do ``fabrication_detail`` do SPDM (read-only)."""
    from .real_sources import _datafy_conn, _rows

    with _datafy_conn() as conn:
        cur = conn.cursor()
        pkg_rows = _rows(cur, _PACKAGE_ONE_SQL, (pk,))
        if not pkg_rows:
            return {"available": False, "error": "package not found", "linked": False, "tables": []}
        package = pkg_rows[0]
        document_id = package.get("document_id")
        tables: list[dict] = []
        if document_id:
            items = _fetch_coverage_items(cur, [int(document_id)])
            spool_plans, spool_cells = _fetch_spool_maps(cur, [int(document_id)])
            docs = _detail_docs(items, {int(document_id)}, spool_plans, spool_cells)
            tables = docs.get(str(int(document_id)), [])

    return {
        "available": True,
        "linked": document_id is not None,
        "tables": tables,
    }


def fabrication_package_detail_safe(pk: int) -> dict:
    try:
        return fabrication_package_detail(pk)
    except Exception as exc:  # pragma: no cover - depende do Postgres externo
        return {"available": False, "error": str(exc), "linked": False, "tables": []}


def fabrication_po_pending(pk: int) -> dict:
    """Modal "Material & PO coverage" — mesmo JSON do fabrication_po_pending
    do SPDM: strip de numeros + itens de fabricacao pendentes e os comprados
    ainda a caminho do patio."""
    from .real_sources import _datafy_conn, _rows

    with _datafy_conn() as conn:
        cur = conn.cursor()
        pkg_rows = _rows(cur, _PACKAGE_ONE_SQL, (pk,))
        if not pkg_rows:
            return {"available": False, "error": "package not found", "linked": False, "rows": []}
        package = pkg_rows[0]
        document_id = package.get("document_id")
        plan_start = _as_date(package.get("plan_start"))
        payload: dict[str, Any] = {
            "available": True,
            "linked": document_id is not None,
            "dwg": package.get("doc_drawing_number") or package.get("drawing_number") or package.get("dwg_key") or "",
            "title": package.get("doc_title") or package.get("name") or "",
            "plan_start": plan_start.isoformat() if plan_start else "",
            "summary": "",
            "rows": [],
        }
        if not document_id:
            return payload
        items = _fetch_coverage_items(cur, [int(document_id)])

    nums = _coverage_index(items).get(int(document_id)) or {
        "total": 0, "covered": 0, "uncovered": 0, "yard": 0, "pct": 0,
        "arrival": "", "sheets_total": 0, "sheets_ready": 0,
    }
    start_risk, start_risk_title = _material_arrival_risk(plan_start, nums["arrival"])
    payload["summary"] = _pend_tooltip(nums)
    payload["nums"] = nums
    payload["start_risk"] = start_risk
    payload["start_risk_title"] = start_risk_title

    def po_entries_with_risk(row: dict) -> list[dict]:
        entries = []
        for entry in row.get("po_entries") or []:
            risk, risk_title = _material_arrival_risk(plan_start, entry.get("expected"))
            entries.append({
                "number": entry.get("number") or "",
                "expected": entry.get("expected") or "",
                "risk": risk,
                "risk_title": risk_title,
            })
        return entries

    rows: list[dict] = []
    fabrication_items = [row for row in items if str(row.get("scope") or "") == "fabrication"]

    # 1) itens pendentes (sem cobertura completa) — bloqueiam a chip vermelha
    for row in fabrication_items:
        chip, chip_label = _detail_item_status(row)
        if chip == "covered":
            continue
        qty = _decimal(row.get("missing_qty"))
        if qty <= 0:
            qty = _decimal(row.get("requested_qty"))
        rows.append({
            "material": str(row.get("description") or "—"),
            "qty": _fmt_qty(qty),
            "unit": str(row.get("unit") or ""),
            "po": str(row.get("po_label") or ""),
            "pos": po_entries_with_risk(row),
            "expected": str(row.get("po_expected_text") or ""),
            "motivo": chip,
            "motivo_label": chip_label,
        })

    # 2) itens comprados mas ainda nao entregues no patio — "Awaiting delivery"
    for row in fabrication_items:
        chip, _label = _detail_item_status(row)
        if chip != "covered":
            continue
        yard_qty = _decimal(row.get("yard_qty"))
        if int(row.get("yard_actual") or 0):
            continue  # ja inteiro no patio
        if yard_qty <= 0 and not int(row.get("has_po") or 0):
            continue
        requested = _decimal(row.get("requested_qty"))
        pending_qty = requested - yard_qty
        if pending_qty <= 0:
            pending_qty = _decimal(row.get("allocated_qty"))
        rows.append({
            "material": str(row.get("description") or "—"),
            "qty": _fmt_qty(pending_qty),
            "unit": str(row.get("unit") or ""),
            "po": str(row.get("po_label") or ""),
            "pos": po_entries_with_risk(row),
            "expected": str(row.get("po_expected_text") or ""),
            "motivo": "aguarda_entrega",
            "motivo_label": "Awaiting delivery",
        })

    payload["rows"] = rows
    return payload


def fabrication_po_pending_safe(pk: int) -> dict:
    try:
        return fabrication_po_pending(pk)
    except Exception as exc:  # pragma: no cover - depende do Postgres externo
        return {"available": False, "error": str(exc), "linked": False, "rows": []}


_EXPEDITE_PACKAGES_SQL = """
select p.code, p.document_id, d.priority
  from fabrication_fabricationpackage p
  join core_document d on d.id = p.document_id
 where p.is_active = true
"""


def fabrication_expedite() -> dict:
    """Modal "POs to expedite" — mesma regra do fabrication_expedite do SPDM:
    POs segurando material de fabricacao ainda nao entregue no patio,
    ordenadas pela prioridade do desenho mais importante afetado."""
    from . import real_sources as rs
    from .real_sources import _datafy_conn, _rows

    with _datafy_conn() as conn:
        cur = conn.cursor()
        packages = _rows(cur, _EXPEDITE_PACKAGES_SQL)
        doc_ids = sorted({int(p["document_id"]) for p in packages})
        if not doc_ids:
            return {"available": True, "rows": []}
        items = _rows(cur, _COVERAGE_ITEMS_SQL, (doc_ids, doc_ids))
        po_rows = _rows(cur, _COVERAGE_PO_SQL, (doc_ids,))

    # escopo de fabricacao por item (a query ja normaliza o scope)
    fabrication_ids = {
        row["material_item_id"]
        for row in items
        if str(row.get("scope") or "") == "fabrication"
    }
    doc_by_item = {row["material_item_id"]: int(row["document_id"]) for row in items}
    by_doc: dict[int, list[dict]] = {}
    for package in packages:
        by_doc.setdefault(int(package["document_id"]), []).append(package)

    yard_cache: dict[Any, bool] = {}
    pos: dict[Any, dict] = {}
    for row in po_rows:
        material_id = row.get("material_item_id")
        if material_id not in fabrication_ids:
            continue
        number = str(row.get("po_number") or row.get("po_original_filename") or "").strip()
        if number.upper().startswith("PO-AVEON-PARALLEL"):
            continue
        po_id = row.get("po_id")
        if po_id not in yard_cache:
            yard_cache[po_id] = rs._po_row_has_yard_actual(row)
        if yard_cache[po_id]:
            continue  # ja entregue no patio — nada a adiantar
        entry = pos.setdefault(po_id, {
            "po": number,
            "expected": str(row.get("po_expected_text") or "").strip(),
            "plan_date": str(row.get("procurement_plan_date") or ""),
            "plan_stage": str(row.get("procurement_plan_stage") or ""),
            "items": 0,
            "drawings": {},
        })
        entry["items"] += 1
        for package in by_doc.get(doc_by_item.get(material_id, -1), []):
            priority = package.get("priority")
            priority = None if priority is None or int(priority) == 999 else int(priority)
            current = entry["drawings"].get(package["code"])
            if current is None or (priority is not None and priority < (current if current is not None else 999)):
                entry["drawings"][package["code"]] = priority

    rows = []
    for entry in pos.values():
        drawings = entry.pop("drawings")
        priorities = [p for p in drawings.values() if p is not None]
        min_priority = min(priorities) if priorities else None
        top = sorted(drawings.items(), key=lambda kv: (kv[1] if kv[1] is not None else 999, kv[0]))
        entry["min_priority"] = min_priority
        entry["drawings_count"] = len(drawings)
        entry["drawings_top"] = [
            code + (f" (P{prio})" if prio is not None else "") for code, prio in top[:3]
        ]
        rows.append(entry)
    rows.sort(key=lambda e: (
        e["min_priority"] if e["min_priority"] is not None else 999,
        -e["drawings_count"],
        e["po"],
    ))
    return {"available": True, "rows": rows[:60]}


def fabrication_expedite_safe() -> dict:
    try:
        return fabrication_expedite()
    except Exception as exc:  # pragma: no cover - depende do Postgres externo
        return {"available": False, "error": str(exc), "rows": []}

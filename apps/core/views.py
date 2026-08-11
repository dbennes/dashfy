from __future__ import annotations

import io
import json
import re
from collections import Counter
from datetime import date, datetime

from django.conf import settings
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.permissions import has_module_permission
from apps.core.datafy_supply import refresh_supply_snapshot, supply_filters_hash
from apps.core.engineering_import import import_engineering_status_workbook
from apps.core.engineering_monitor_import import import_engineering_monitor_workbook, normalize_monitor_discipline
from apps.core.model_selection import SelectionTooLarge, selection_glb_path
from apps.core.p6_import import import_p6_curves_workbook
from apps.core.supply_snapshot_filters import normalized_supply_snapshot_filters
from apps.exports.models import ExportLog
from apps.core import real_sources

from .models import Announcement, DatafySupplySnapshot, EngineeringMonitorImport, EngineeringStatusImport


def _dashboard_filters_from_request(request):
    return {
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "discipline": request.GET.get("discipline", ""),
        "engineering_discipline": request.GET.get("engineering_discipline", ""),
        "engineering_status": request.GET.get("engineering_status", ""),
        "engineering_issue_status": request.GET.get("engineering_issue_status", ""),
        "engineering_revision": request.GET.get("engineering_revision", ""),
        "engineering_responsible": request.GET.get("engineering_responsible", ""),
        "engineering_q": request.GET.get("engineering_q", ""),
        "supply_priority": request.GET.get("supply_priority", ""),
        "supply_drawing_q": request.GET.get("supply_drawing_q", ""),
        "supply_revision": request.GET.get("supply_revision", ""),
        "supply_discipline": request.GET.get("supply_discipline", ""),
        "supply_line": request.GET.get("supply_line", ""),
        "supply_table": request.GET.get("supply_table", ""),
        "supply_page": request.GET.get("supply_page", ""),
        "supply_item": request.GET.get("supply_item", ""),
        "supply_family": request.GET.get("supply_family", ""),
        "supply_code_q": request.GET.get("supply_code_q", ""),
        "supply_description_q": request.GET.get("supply_description_q", ""),
        "supply_fab_min": request.GET.get("supply_fab_min", ""),
        "supply_erection_min": request.GET.get("supply_erection_min", ""),
        "campaign": request.GET.get("campaign", ""),
        "contract_week": request.GET.get("contract_week", ""),
        "min_readiness": request.GET.get("min_readiness", ""),
    }


def _material_row_column_text(row, column):
    if column == "drawing":
        return row.get("drawing_number") or row.get("original_filename") or "-"
    if column == "requested":
        return f"{row.get('requested_qty') or 0} {row.get('unit') or ''}"
    if column == "allocated":
        return f"{row.get('allocated_qty') or 0} {row.get('unit') or ''}"
    if column == "missing":
        return f"{row.get('missing_qty') or 0} {row.get('unit') or ''}"
    if column == "stock":
        if row.get("stock_free_na"):
            return "n/a"
        return f"{row.get('stock_free_qty') or 0} {row.get('unit') or ''}"
    if column == "po":
        return row.get("po_covering") or "No linked PO"

    field_map = {
        "priority": "priority",
        "revision": "revision",
        "discipline": "discipline",
        "line": "line",
        "table": "table_name",
        "page": "page_number",
        "item": "item_number",
        "family": "family",
        "code": "cpmtocode",
        "description": "description",
    }
    field = field_map.get(column)
    if not field:
        return ""
    value = row.get(field)
    return "-" if value in (None, "") else str(value)


def _material_row_numeric_value(row, column):
    field_map = {
        "priority": "priority",
        "page": "page_number",
        "requested": "requested_qty",
        "allocated": "allocated_qty",
        "missing": "missing_qty",
        "stock": "stock_free_qty",
    }
    field = field_map.get(column)
    if not field:
        return 0.0
    try:
        return float(row.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def _supply_lookup_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _supply_split_lookup_values(value):
    output = []
    for part in re.split(r"[,;\n]+", str(value or "")):
        clean = re.sub(r"\s+\+\d+$", "", part).strip()
        if clean and clean != "-":
            output.append(clean)
    return output


def _supply_float_value(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _supply_int_value(value, fallback=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _supply_date_iso(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else text


def _supply_po_delivery_pairs(value):
    pairs = []
    for part in str(value or "").split(";;"):
        if not part.strip():
            continue
        po, _, expected = part.partition("::")
        po = po.strip()
        if not po:
            continue
        pairs.append({
            "po": po,
            "expected_date": _supply_date_iso(expected.strip()),
        })
    return pairs


def _supply_material_po_numbers(row):
    return [
        value for value in _supply_split_lookup_values(row.get("po_covering"))
        if _supply_lookup_text(value) not in {"", "-", "no linked po", "covered"}
    ]


def _supply_enrich_po_delivery(rows):
    po_by_row = []
    all_pos = set()
    for row in rows:
        pos = _supply_material_po_numbers(row)
        po_by_row.append((row, pos))
        all_pos.update(pos)
    if not all_pos:
        return

    lookup = real_sources.datafy_po_delivery_lookup(all_pos)
    if not lookup:
        return
    for row, pos in po_by_row:
        pairs = [
            lookup.get(po.upper())
            for po in pos
            if lookup.get(po.upper())
        ]
        if not pairs:
            continue
        if not row.get("po_delivery_pairs"):
            row["po_delivery_pairs"] = ";;".join(
                f"{pair.get('po') or ''}::{pair.get('expected_date') or ''}"
                for pair in pairs
                if pair.get("po")
            )
        dates = [
            pair.get("expected_date")
            for pair in pairs
            if pair.get("expected_date")
        ]
        if dates:
            if not row.get("po_expected_date"):
                row["po_expected_date"] = dates[0]
            if not row.get("po_expected_dates"):
                row["po_expected_dates"] = ", ".join(dict.fromkeys(dates))


def _supply_size_hint(row):
    line = str(row.get("line") or "")
    line_match = re.match(r'\s*(\d+(?:[.,]\d+)?)\s*"', line)
    if line_match:
        return f'{line_match.group(1).replace(",", ".")}"'

    text = f"{row.get('description') or ''} {row.get('cpmtocode') or ''}"
    desc_match = re.search(r'(?<!\d)(\d+(?:[.,]\d+)?\s*(?:"|in\b|inch\b|pol\b))', text, re.IGNORECASE)
    if desc_match:
        return desc_match.group(1).replace(" ", "")
    return ""


def _supply_material_match_tokens(row):
    text = _supply_lookup_text(
        " ".join(
            str(row.get(field) or "")
            for field in ("family", "cpmtocode", "description")
        )
    )
    tokens = []

    def add(*items):
        for item in items:
            if item and item not in tokens:
                tokens.append(item)

    if re.search(r"\bvalve\b|valvula", text):
        add("VALVE")
    if re.search(r"\bgasket\b|junta", text):
        add("GASKET")
    if re.search(r"stud\s*bolt|\bbolt\b|\bnut\b|parafuso|porca", text):
        add("BOLT", "GENSEC")
    instrument_like = bool(re.search(r"\binstrument\b|transmitter|datasheet|\b04-[a-z0-9-]+", text))
    if re.search(r"\breducer\b|red\s+(?:ecc|conc)|\bptre[cn]?\b", text):
        add("REDUCER")
    blind_flange = bool(re.search(r"\bfblind\b|blind\s+flange|flg\s*bld|flg\s*blind|\bptfbc\b", text))
    weld_neck_flange = bool(re.search(r"flg\s*wn|weld\s*neck|weldneck|\bptfwc\b", text))
    if re.search(r"flangolet|flgol|weldolet|sockolet|\bolet\b", text):
        add("OLET", "FLANGE")
    elif blind_flange:
        add("FBLIND", "FLANGE")
    elif re.search(r"\bflange\b|\bflg\b", text) or (
        not instrument_like and re.search(r"flanged", text)
    ):
        if weld_neck_flange:
            add("FLANGE_WN")
        add("FLANGE")
    if re.search(r"trunnion|trunion|trunn|pipe support|support|shoe|guide|repad|base plate|attachment", text):
        add("ATTACHMENT", "PCOMPONENT", "TRUNNION")
    if re.search(r"\belbow\b", text):
        add("ELBOW")
    if re.search(r"\bbend\b", text):
        add("BEND")
    if re.search(r"\btee\b", text):
        add("TEE")
    if re.search(r"\bcap\b", text):
        add("CAP")
    if not tokens and re.search(r"\bpipe\b|\btube\b", text):
        add("TUBE")
    return tokens


def _supply_is_3d_support_item(row):
    text = _supply_lookup_text(
        " ".join(
            str(row.get(field) or "")
            for field in ("family", "cpmtocode", "description")
        )
    )
    return bool(re.search(
        r"pipe support|shoe|guide|special support|trunnion|trunion|line stop|support",
        text,
    ))


def _supply_3d_material_payload(row):
    requested = _supply_float_value(row.get("requested_qty"))
    allocated = _supply_float_value(row.get("allocated_qty"))
    missing = _supply_float_value(row.get("missing_qty"))
    stock = _supply_float_value(row.get("stock_free_qty"))
    is_support_attention = _supply_is_3d_support_item(row)
    return {
        "material_item_id": row.get("material_item_id"),
        "drawing": row.get("drawing_number") or row.get("original_filename") or "-",
        "line": row.get("line") or "-",
        "scope": row.get("scope") or "",
        "scope_label": row.get("scope_label") or "",
        "table": row.get("table_name") or "-",
        "page": row.get("page_number"),
        "item": row.get("item_number") or "-",
        "family": row.get("family") or "",
        "code": row.get("cpmtocode") or "",
        "description": row.get("description") or "",
        "requested_qty": requested,
        "allocated_qty": allocated,
        "missing_qty": missing,
        "stock_free_qty": stock,
        "stock_free_na": bool(row.get("stock_free_na")),
        "unit": row.get("unit") or "",
        "po": row.get("po_covering") or "",
        "po_list": _supply_split_lookup_values(row.get("po_covering")),
        "po_expected_date": _supply_date_iso(row.get("po_expected_date")),
        "po_expected_dates": [
            _supply_date_iso(value)
            for value in _supply_split_lookup_values(row.get("po_expected_dates"))
            if _supply_date_iso(value)
        ],
        "po_delivery_pairs": _supply_po_delivery_pairs(row.get("po_delivery_pairs")),
        "status": row.get("status") or "",
        "status_label": row.get("status_label") or "",
        "size": _supply_size_hint(row),
        "attention": is_support_attention,
        "attention_label": "Support/trunnion only; not counted as missing material" if is_support_attention else "",
        "match_tokens": [] if is_support_attention else _supply_material_match_tokens(row),
    }


@login_required
def home_view(request):
    """Cockpit gerencial consumindo somente bases reais integradas."""
    user = request.user

    modules = [
        {
            "key": "datafy",
            "label": "Datafy",
            "desc": "Dados operacionais, indicadores e KPIs.",
            "icon": "bi-bar-chart-fill",
            "color": "primary",
            "url": "datafy:home",
            "allowed": has_module_permission(user, "datafy"),
        },
        {
            "key": "taskfy",
            "label": "Taskfy",
            "desc": "Gestao de tarefas, status e responsaveis.",
            "icon": "bi-kanban-fill",
            "color": "success",
            "url": "taskfy:home",
            "allowed": has_module_permission(user, "taskfy"),
        },
        {
            "key": "schedule",
            "label": "Schedule",
            "desc": "Cronogramas, marcos e calendario.",
            "icon": "bi-calendar3",
            "color": "warning",
            "url": "schedule:home",
            "allowed": has_module_permission(user, "schedule"),
        },
        {
            "key": "eclic",
            "label": "ECLIC",
            "desc": "Documentacoes e integracao com API.",
            "icon": "bi-file-earmark-text-fill",
            "color": "danger",
            "url": "eclic:home",
            "allowed": has_module_permission(user, "eclic"),
        },
    ]

    now = timezone.now()
    announcements = Announcement.objects.filter(is_active=True)
    announcements = [
        a for a in announcements
        if (a.starts_at is None or a.starts_at <= now)
        and (a.ends_at is None or a.ends_at >= now)
    ][:5]

    active_users_24h = User.objects.filter(
        last_seen__gte=now - timezone.timedelta(hours=24)
    ).count()
    total_users = User.objects.filter(is_active=True).count()
    dashboard_filters = _dashboard_filters_from_request(request)
    manager = real_sources.management_dashboard(dashboard_filters)
    charts_payload = manager.get("charts", {})

    context = {
        "modules": modules,
        "announcements": announcements,
        "manager": manager,
        "show_login_boot": bool(request.session.pop("show_login_boot", False)),
        "sources": {
            "datafy": manager.get("datafy", {}),
            "taskfy": manager.get("taskfy", {}),
            "p6": manager.get("p6", {}),
        },
        "chart_p6_physical_curve": json.dumps(
            charts_payload.get("p6_physical_curve", {}),
            default=real_sources.json_default,
        ),
        "chart_p6_area_performance": json.dumps(
            charts_payload.get("p6_area_performance", {}),
            default=real_sources.json_default,
        ),
        "chart_p6_monthly_units": json.dumps(
            charts_payload.get("p6_monthly_units", {}),
            default=real_sources.json_default,
        ),
        "chart_s_curve": json.dumps(charts_payload.get("s_curve", {}), default=real_sources.json_default),
        "chart_weekly_histogram": json.dumps(charts_payload.get("weekly_histogram", {}), default=real_sources.json_default),
        "chart_gantt": json.dumps(charts_payload.get("gantt", {}), default=real_sources.json_default),
        "chart_dfr_by_discipline": json.dumps(charts_payload.get("dfr_by_discipline", {}), default=real_sources.json_default),
        "chart_engineering_revisions": json.dumps(charts_payload.get("engineering_revisions", {}), default=real_sources.json_default),
        "chart_engineering_status": json.dumps(charts_payload.get("engineering_status", {}), default=real_sources.json_default),
        "chart_line_readiness": json.dumps(charts_payload.get("line_readiness", {}), default=real_sources.json_default),
        "kpis": {
            "active_users_24h": active_users_24h,
            "total_users": total_users,
            "now": now,
        },
    }
    return render(request, "core/home.html", context)


def _aveon_material_payload():
    data_path = settings.BASE_DIR / "static" / "data" / "aveon_material_availability.json"
    with data_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@login_required
def aveon_material_availability_view(request):
    """React workbook view generated from the AVEON material availability file."""
    payload = _aveon_material_payload()
    return render(
        request,
        "core/aveon_material_availability.html",
        {
            "aveon_payload": payload,
            "aveon_meta": payload.get("meta", {}),
            "sources": {
                "datafy": {"available": True},
                "taskfy": {"available": True},
                "p6": {"available": True},
            },
        },
    )


@login_required
def material_rows_page_view(request):
    """Return one server-side page of DATAFY material rows for the heavy supply grid."""
    dashboard_filters = _dashboard_filters_from_request(request)
    manager = real_sources.management_dashboard(dashboard_filters)
    rows = list(manager.get("material", {}).get("material_rows") or [])
    valid_columns = {
        "priority", "drawing", "revision", "discipline", "line", "table", "page", "item",
        "family", "code", "description", "requested", "allocated", "missing", "stock", "po",
    }
    numeric_columns = {"priority", "page", "requested", "allocated", "missing", "stock"}

    status = request.GET.get("status", "").strip()
    if status:
        rows = [row for row in rows if str(row.get("status") or "") == status]

    query = request.GET.get("q", "").strip().lower()
    if query:
        def row_text(row):
            fields = (
                "priority", "drawing_number", "original_filename", "revision",
                "discipline", "line", "table_name", "page_number", "item_number",
                "family", "cpmtocode", "description", "po_covering",
            )
            return " ".join(str(row.get(field) or "") for field in fields).lower()
        rows = [row for row in rows if query in row_text(row)]

    for column in valid_columns:
        contains_value = request.GET.get(f"cf_{column}", "").strip().lower()
        if contains_value:
            rows = [
                row for row in rows
                if contains_value in _material_row_column_text(row, column).lower()
            ]

        exact_value = request.GET.get(f"cs_{column}", "").strip().lower()
        if exact_value:
            rows = [
                row for row in rows
                if _material_row_column_text(row, column).lower() == exact_value
            ]

    sort_column = request.GET.get("sort_col", "").strip()
    sort_dir = -1 if request.GET.get("sort_dir") == "-1" else 1
    if sort_column in valid_columns:
        if sort_column in numeric_columns:
            rows.sort(
                key=lambda row: _material_row_numeric_value(row, sort_column),
                reverse=sort_dir < 0,
            )
        else:
            rows.sort(
                key=lambda row: _material_row_column_text(row, sort_column).casefold(),
                reverse=sort_dir < 0,
            )

    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = int(request.GET.get("page_size", "300"))
    except ValueError:
        page_size = 300
    page_size = max(100, min(page_size, 600))

    total = len(rows)
    max_page = max(1, (total + page_size - 1) // page_size)
    page = min(page, max_page)
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    page_rows = rows[start:end]
    html = render_to_string("core/partials/material_rows.html", {"rows": page_rows})
    return JsonResponse({
        "html": html,
        "page": page,
        "page_size": page_size,
        "total": total,
        "start": start + 1 if total else 0,
        "end": end,
        "has_prev": page > 1,
        "has_next": end < total,
    })


@login_required
def material_items_3d_view(request):
    """Return the DATAFY material rows that should drive the 3D missing overlay."""
    dashboard_filters = _dashboard_filters_from_request(request)
    manager = real_sources.management_dashboard(dashboard_filters)
    rows = [dict(row) for row in manager.get("material", {}).get("material_rows") or []]

    drawing = _supply_lookup_text(request.GET.get("drawing", ""))
    line_values = {
        _supply_lookup_text(value)
        for value in _supply_split_lookup_values(request.GET.get("line", ""))
    }
    line_values.discard("")
    scope = _supply_lookup_text(request.GET.get("scope", ""))
    status = _supply_lookup_text(request.GET.get("status", "missing")) or "missing"

    if drawing:
        rows = [
            row for row in rows
            if any(
                drawing == candidate
                or drawing in candidate
                or candidate in drawing
                for candidate in (
                    _supply_lookup_text(row.get("drawing_number")),
                    _supply_lookup_text(row.get("original_filename")),
                )
                if candidate
            )
        ]

    if line_values:
        rows = [
            row for row in rows
            if _supply_lookup_text(row.get("line")) in line_values
        ]

    if scope:
        rows = [
            row for row in rows
            if _supply_lookup_text(row.get("scope")) == scope
        ]

    if status in {"missing", "pending"}:
        rows = [
            row for row in rows
            if _supply_float_value(row.get("missing_qty")) > 0
        ]

    _supply_enrich_po_delivery(rows)

    rows.sort(key=lambda row: (
        _supply_int_value(row.get("priority"), 999999),
        _supply_lookup_text(row.get("scope")),
        _supply_int_value(row.get("page_number"), 0),
        _supply_int_value(row.get("item_number"), 999999),
        _supply_lookup_text(row.get("item_number")),
        _supply_lookup_text(row.get("family")),
        _supply_lookup_text(row.get("cpmtocode")),
    ))

    missing_rows = [
        row for row in rows
        if _supply_float_value(row.get("missing_qty")) > 0
        and not _supply_is_3d_support_item(row)
    ]
    attention_rows = [
        row for row in rows
        if _supply_float_value(row.get("missing_qty")) > 0
        and _supply_is_3d_support_item(row)
    ]
    payload_rows = [_supply_3d_material_payload(row) for row in rows[:80]]
    missing_payload_rows = [_supply_3d_material_payload(row) for row in missing_rows]
    families = sorted({row["family"] for row in missing_payload_rows if row.get("family")})
    tokens = []
    for row in missing_payload_rows:
        for token in row.get("match_tokens") or []:
            if token not in tokens:
                tokens.append(token)

    return JsonResponse({
        "rows": payload_rows,
        "total": len(rows),
        "returned": len(payload_rows),
        "families": families,
        "tokens": tokens,
        "missing_item_count": len(missing_rows),
        "missing_qty_total": sum(_supply_float_value(row.get("missing_qty")) for row in missing_rows),
        "attention_item_count": len(attention_rows),
    })


@login_required
def search_view(request):
    """Busca global simples (preenchida pelos modulos posteriormente)."""
    q = request.GET.get("q", "").strip()
    return render(request, "core/search.html", {"q": q, "results": []})


@login_required
@require_POST
def import_p6_curves_view(request):
    """Importa o Annex III de curvas P6 para a base do sistema."""
    if not getattr(request.user, "is_admin", False):
        raise PermissionDenied("Somente administradores podem importar curvas P6.")

    upload = request.FILES.get("p6_curves_file")
    if not upload:
        messages.error(request, "Selecione o arquivo XLSX de curvas P6 antes de importar.")
        return redirect(reverse("core:home") + "#s00")

    try:
        batch = import_p6_curves_workbook(upload, imported_by=request.user)
    except Exception as exc:
        messages.error(request, f"Falha ao importar curvas P6: {exc}")
    else:
        management = getattr(batch, "management_snapshot", None)
        management_msg = ""
        if management:
            management_msg = (
                f", {management.monthly_point_count} meses de carga S03 "
                f"e {management.area_count} areas gerenciais"
            )
        messages.success(
            request,
            (
                "Curvas P6 importadas para a base do sistema: "
                f"{batch.progress_row_count} linhas PMS, "
                f"{batch.curve_point_count} pontos semanais e "
                f"{batch.executive_row_count} areas executivas"
                f"{management_msg}."
            ),
        )
    return redirect(reverse("core:home") + "#s00")


@login_required
@require_POST
def import_engineering_status_view(request):
    """Importa o XLSX DED de status de engenharia para a base do sistema."""
    if not getattr(request.user, "is_admin", False):
        raise PermissionDenied("Somente administradores podem importar a base DED de engenharia.")

    upload = request.FILES.get("engineering_status_file")
    if not upload:
        messages.error(request, "Selecione o arquivo XLSX DED antes de importar.")
        return redirect(reverse("core:home") + "#s01")

    try:
        batch = import_engineering_status_workbook(upload, imported_by=request.user)
    except Exception as exc:
        messages.error(request, f"Falha ao importar DED engenharia: {exc}")
    else:
        messages.success(
            request,
            (
                "DED engenharia importado para a base do sistema: "
                f"{batch.document_count} documentos, "
                f"{batch.discipline_count} disciplinas e "
                f"{batch.summary_row_count} linhas de resumo."
            ),
        )
    return redirect(reverse("core:home") + "#s01")


@login_required
@require_POST
def import_engineering_monitor_view(request):
    """Importa a planilha bruta de engenharia ou a base editada."""
    if not getattr(request.user, "is_admin", False):
        raise PermissionDenied("Somente administradores podem importar o monitor de engenharia.")

    upload = request.FILES.get("engineering_monitor_file")
    if not upload:
        messages.error(request, "Selecione o arquivo XLSX do monitor de engenharia antes de importar.")
        return redirect(reverse("core:home") + "#s01-monitor")

    try:
        batch = import_engineering_monitor_workbook(upload, imported_by=request.user)
    except Exception as exc:
        messages.error(request, f"Falha ao importar monitor de engenharia: {exc}")
    else:
        messages.success(
            request,
            (
                "Base de engenharia importada: "
                f"{batch.monitored_document_count} documentos contabilizados, "
                f"{batch.discipline_count} disciplinas e "
                f"{batch.excluded_count} linhas fora da contagem."
            ),
        )
    return redirect(reverse("core:home") + "#s01-monitor")


def _monitor_export_status_label(value) -> str:
    text = str(value or "").strip().upper()
    if text == "UNDER REVIEW":
        return "MABU UNDER REVIEW"
    if text == "AFC CODE 3A":
        return "AFC 3A"
    return text


def _monitor_excluded_reason_label(value, *, is_monitored: bool = True) -> str:
    text = str(value or "").strip()
    if not is_monitored and not text:
        return "Disciplina fora do monitoramento"
    labels = {
        "Outside configured sample folders": "Fora das pastas configuradas para a amostra",
        "Excluded sample folder": "Pasta removida da amostra por regra",
        "Cancelled document status": "Status documental cancelado",
        "Excluded purpose next issue": "Purpose Next Issue removido por regra",
        "Revision contains field mark": "Revisao contem ponto usado como marca de campo",
        "IFF without approved return code": "IFF sem retorno CODE 1, CODE 2 ou CODE 3",
        "IFA RA-7769 excluded": "IFA RA-7769 desconsiderado por regra",
        "IFR 3323 excluded": "IFR 3323 desconsiderado por regra",
        "Purpose next issue outside monitored statuses": "Purpose Next Issue fora das categorias monitoradas",
        "Excluded document number": "Numero do documento excluido por regra",
        "Vendor directory": "Diretorio Vendor",
        "Not applicable/cancelled": "Nao aplicavel/cancelado",
        "Excluded title": "Titulo excluido por regra",
        "Cancelled revision X": "Revisao X cancelada",
        "Rejected": "Rejeitado",
        "Unmapped": "Status nao mapeado",
    }
    return labels.get(text, text)


def _monitor_export_doc(doc: dict) -> dict:
    discipline = (
        normalize_monitor_discipline(doc.get("source_discipline") or doc.get("discipline"), doc.get("title"))
        or normalize_monitor_discipline(doc.get("discipline"), doc.get("title"))
    )
    if discipline and discipline != doc.get("discipline"):
        return {**doc, "discipline": discipline}
    return doc


@login_required
def export_engineering_monitor_view(request):
    """Exporta a base de engenharia normalizada e editavel para virar fonte oficial."""
    latest = EngineeringMonitorImport.objects.filter(is_active=True).first()
    if latest is None:
        messages.error(request, "Nao ha base de engenharia ativa para exportar.")
        return redirect(reverse("core:home") + "#s01-monitor")

    payload = latest.payload or {}
    docs = [_monitor_export_doc(dict(doc)) for doc in list(payload.get("documents") or [])]
    docs.sort(key=lambda doc: (int(doc.get("row_number") or 0), str(doc.get("document_number") or "")))

    output = io.BytesIO()
    import xlsxwriter

    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_urls": False})
    header_fmt = workbook.add_format({
        "bold": True,
        "font_color": "#f8fafc",
        "bg_color": "#111827",
        "border": 1,
        "border_color": "#334155",
        "text_wrap": True,
    })
    text_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "text_wrap": True})
    count_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "num_format": "#,##0"})
    yes_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "bg_color": "#dcfce7"})
    no_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "bg_color": "#fee2e2"})
    note_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "bg_color": "#fff7ed", "text_wrap": True})
    title_fmt = workbook.add_format({"bold": True, "font_size": 14, "font_color": "#111827"})

    base_sheet = workbook.add_worksheet("Base Engenharia")
    columns = [
        ("Documento", 34),
        ("Titulo", 52),
        ("Disciplina", 22),
        ("Disciplina origem", 26),
        ("Revisao", 10),
        ("Contabilizar", 14),
        ("Status normalizado", 20),
        ("Motivo desconsiderado", 30),
        ("Status documento", 22),
        ("Issue Status", 30),
        ("Last transmittal purpose", 26),
        ("Purpose Next Issue", 30),
        ("11-Cpy_Approval_Code", 26),
        ("14-Tr_Aol-Fabrication", 24),
        ("Diretorio", 46),
        ("Observacao admin", 34),
    ]
    for col, (label, width) in enumerate(columns):
        base_sheet.write(0, col, label, header_fmt)
        base_sheet.set_column(col, col, width)

    status_options = [
        "NI",
        "IFR",
        "IFA",
        "IFI",
        "AFC 1",
        "AFC 3",
        "AFC 3A",
        "MABU UNDER REVIEW",
        "N/A",
        "REJECTED",
        "UNCLASSIFIED",
    ]
    for row_idx, doc in enumerate(docs, start=1):
        is_monitored = bool(doc.get("is_monitored"))
        is_countable = bool(is_monitored and doc.get("is_countable"))
        contabilizar = "SIM" if is_countable else "NAO"
        status = _monitor_export_status_label(doc.get("status_bucket")) if is_countable else ""
        motivo = "" if is_countable else _monitor_excluded_reason_label(doc.get("excluded_reason"), is_monitored=is_monitored)
        values = [
            doc.get("document_number") or "",
            doc.get("title") or "",
            doc.get("discipline") or "",
            doc.get("source_discipline") or "",
            doc.get("revision") or "",
            contabilizar,
            status,
            motivo,
            doc.get("document_status_original") or doc.get("document_status_effective") or "",
            doc.get("issue_status") or "",
            doc.get("last_transmittal_purpose") or "",
            doc.get("purpose_next_issue") or "",
            doc.get("approval_code") or "",
            doc.get("fabrication_ref") or "",
            doc.get("directory") or "",
            "",
        ]
        for col, value in enumerate(values):
            fmt = yes_fmt if col == 5 and contabilizar == "SIM" else no_fmt if col == 5 else note_fmt if col == len(columns) - 1 else text_fmt
            base_sheet.write(row_idx, col, value, fmt)

    last_row = max(len(docs), 1)
    base_sheet.autofilter(0, 0, last_row, len(columns) - 1)
    base_sheet.freeze_panes(1, 0)
    base_sheet.data_validation(1, 5, last_row, 5, {"validate": "list", "source": ["SIM", "NAO"]})
    base_sheet.data_validation(1, 6, last_row, 6, {"validate": "list", "source": status_options})

    summary_sheet = workbook.add_worksheet("Resumo")
    summary_sheet.write(0, 0, "Base de engenharia editavel", title_fmt)
    summary_sheet.write(1, 0, "Edite Contabilizar e Status normalizado. Depois importe este arquivo novamente para tornar a base oficial.", text_fmt)
    summary_rows = [
        ("Importacao", f"#{latest.pk} - {latest.original_filename}"),
        ("Linhas brutas", latest.document_count),
        ("Contabilizadas", latest.monitored_document_count),
        ("Desconsideradas", latest.excluded_count),
        ("Aba para editar", "Base Engenharia"),
    ]
    summary_sheet.write_row(3, 0, ["Item", "Valor"], header_fmt)
    for row_idx, (label, value) in enumerate(summary_rows, start=4):
        summary_sheet.write(row_idx, 0, label, text_fmt)
        summary_sheet.write(row_idx, 1, value, count_fmt if isinstance(value, int) else text_fmt)
    summary_sheet.set_column(0, 0, 24)
    summary_sheet.set_column(1, 1, 64)

    workbook.close()

    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    filename = f"base_engenharia_editavel_{timestamp}.xlsx"
    export_user = getattr(request.user, "_wrapped", request.user)
    if not getattr(export_user, "is_authenticated", False):
        export_user = None
    ExportLog.objects.create(
        user=export_user,
        filename=filename,
        file_format="xlsx",
        module="engineering-monitor",
        rows=len(docs),
        query_params="",
    )
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _engineering_export_afc_code(value) -> str:
    text = str(value or "").strip()
    upper = text.upper()
    if not text:
        return ""
    if upper == "MABU" or "UNDER REVIEW" in upper:
        return "UNDER REVIEW"
    return text


def _engineering_export_bucket(row) -> str:
    group = str(row.doc_status_group or "").strip().upper()
    afc_code = _engineering_export_afc_code(row.afc_code)
    if group == "NOT ISSUED":
        return "NI"
    if group in {"IFR", "IFA"}:
        return group
    if group == "AFC":
        if afc_code == "UNDER REVIEW":
            return "UNDER REVIEW"
        if afc_code in {"1", "3"}:
            return f"AFC {afc_code}"
        return f"AFC {afc_code}".strip() if afc_code else "AFC"
    return row.doc_status or row.document_status or "-"


def _engineering_status_export_queryset(request):
    latest = (
        EngineeringStatusImport.objects
        .filter(is_active=True)
        .prefetch_related("discipline_summaries")
        .first()
    )
    if latest is None:
        return None, None

    qs = latest.documents.all().order_by("discipline", "doc_status_group", "afc_code", "document_number")
    discipline = request.GET.get("engineering_discipline") or request.GET.get("discipline") or ""
    status = request.GET.get("engineering_status", "").strip()
    issue_status = request.GET.get("engineering_issue_status", "").strip()
    responsible = request.GET.get("engineering_responsible", "").strip()
    revision = request.GET.get("engineering_revision", "").strip()
    query = request.GET.get("engineering_q", "").strip()

    if discipline:
        qs = qs.filter(discipline=discipline)
    if status:
        status_q = (
            Q(doc_status__iexact=status)
            | Q(document_status__iexact=status)
            | Q(doc_status_group__iexact=status)
            | Q(afc_code__iexact=status)
        )
        if status.upper() == "UNDER REVIEW":
            status_q |= Q(afc_code__iexact="MABU") | Q(afc_code__icontains="UNDER REVIEW")
        qs = qs.filter(status_q)
    if issue_status:
        qs = qs.filter(issue_status__iexact=issue_status)
    if responsible:
        qs = qs.filter(responsible__iexact=responsible)
    if revision in {"R", "A", "C"}:
        qs = qs.filter(revision_family=revision)
    if query:
        qs = qs.filter(
            Q(document_number__icontains=query)
            | Q(title__icontains=query)
            | Q(discipline__icontains=query)
            | Q(revision__icontains=query)
            | Q(doc_status__icontains=query)
            | Q(document_status__icontains=query)
            | Q(issue_status__icontains=query)
            | Q(responsible__icontains=query)
            | Q(fabrication_ref__icontains=query)
        )
    return latest, qs


@login_required
def export_engineering_status_view(request):
    """Exporta desenhos/documentos DED e status do snapshot ativo."""
    latest, qs = _engineering_status_export_queryset(request)
    if latest is None or qs is None:
        messages.error(request, "Nao ha snapshot DED ativo na base do sistema para exportar.")
        return redirect(reverse("core:home") + "#s01")

    rows = list(qs)
    remarks_by_discipline = {
        row.discipline: row.remarks
        for row in latest.discipline_summaries.all()
    }

    output = io.BytesIO()
    import xlsxwriter

    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_urls": False})
    header_fmt = workbook.add_format({
        "bold": True,
        "font_color": "#f8fafc",
        "bg_color": "#111827",
        "border": 1,
        "border_color": "#334155",
    })
    text_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb"})
    date_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "num_format": "dd/mm/yyyy"})
    count_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "num_format": "#,##0"})
    note_fmt = workbook.add_format({"border": 1, "border_color": "#e5e7eb", "text_wrap": True})

    documents_sheet = workbook.add_worksheet("Drawings")
    columns = [
        ("Drawing / Documento", 28),
        ("Titulo", 48),
        ("Disciplina", 22),
        ("Revisao", 10),
        ("Status", 18),
        ("Status DED", 22),
        ("Status documento", 20),
        ("AFC code", 16),
        ("Status emissao", 22),
        ("Responsavel", 24),
        ("Workflow inicio", 16),
        ("Workflow fim", 16),
        ("Fabrication ref.", 24),
        ("Observacao disciplina", 42),
    ]
    for col, (label, width) in enumerate(columns):
        documents_sheet.write(0, col, label, header_fmt)
        documents_sheet.set_column(col, col, width)

    status_counter: Counter[str] = Counter()
    discipline_counter: Counter[str] = Counter()
    for row_idx, row in enumerate(rows, start=1):
        bucket = _engineering_export_bucket(row)
        afc_code = _engineering_export_afc_code(row.afc_code)
        status_counter[bucket] += 1
        discipline_counter[row.discipline or "-"] += 1
        values = [
            row.document_number,
            row.title,
            row.discipline,
            row.revision,
            bucket,
            row.doc_status,
            row.document_status,
            afc_code,
            row.issue_status,
            row.responsible,
            row.workflow_start,
            row.workflow_end,
            row.fabrication_ref,
            remarks_by_discipline.get(row.discipline, ""),
        ]
        for col, value in enumerate(values):
            fmt = date_fmt if col in {10, 11} and value else note_fmt if col == 13 else text_fmt
            documents_sheet.write(row_idx, col, value or "", fmt)
    documents_sheet.autofilter(0, 0, max(len(rows), 1), len(columns) - 1)
    documents_sheet.freeze_panes(1, 0)

    status_sheet = workbook.add_worksheet("Status")
    status_sheet.write_row(0, 0, ["Status", "Drawings"], header_fmt)
    status_order = ["NI", "IFR", "IFA", "AFC 1", "AFC 3", "UNDER REVIEW", "AFC"]
    sorted_statuses = [key for key in status_order if key in status_counter]
    sorted_statuses += sorted(key for key in status_counter if key not in set(sorted_statuses))
    for row_idx, key in enumerate(sorted_statuses, start=1):
        status_sheet.write(row_idx, 0, key, text_fmt)
        status_sheet.write(row_idx, 1, status_counter[key], count_fmt)
    status_sheet.set_column(0, 0, 24)
    status_sheet.set_column(1, 1, 14)
    status_sheet.autofilter(0, 0, max(len(sorted_statuses), 1), 1)

    discipline_sheet = workbook.add_worksheet("Disciplinas")
    discipline_sheet.write_row(0, 0, ["Disciplina", "Drawings"], header_fmt)
    for row_idx, (discipline, total) in enumerate(
        sorted(discipline_counter.items(), key=lambda pair: (-pair[1], pair[0])),
        start=1,
    ):
        discipline_sheet.write(row_idx, 0, discipline, text_fmt)
        discipline_sheet.write(row_idx, 1, total, count_fmt)
    discipline_sheet.set_column(0, 0, 28)
    discipline_sheet.set_column(1, 1, 14)
    discipline_sheet.autofilter(0, 0, max(len(discipline_counter), 1), 1)

    workbook.close()

    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    filename = f"ded_drawings_status_{timestamp}.xlsx"
    export_user = getattr(request.user, "_wrapped", request.user)
    if not getattr(export_user, "is_authenticated", False):
        export_user = None
    ExportLog.objects.create(
        user=export_user,
        filename=filename,
        file_format="xlsx",
        module="engineering",
        rows=len(rows),
        query_params=request.GET.urlencode()[:1000],
    )
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _json_ready(value):
    return json.loads(json.dumps(value, default=real_sources.json_default, ensure_ascii=False))


def _supply_snapshot_counts(payload: dict) -> tuple[int, int, int]:
    flow = payload.get("material_flow") or {}
    campaign_views = payload.get("supply_campaign_views") or []
    total_drawings = sum(
        int((view.get("totals") or {}).get("drawings") or 0)
        for view in campaign_views
    )
    return (
        int(flow.get("total") or 0),
        total_drawings,
        len(payload.get("material_rows") or []),
    )


def _supply_snapshot_redirect(request):
    target = reverse("core:home")
    if request.GET.urlencode():
        target = f"{target}?{request.GET.urlencode()}"
    return f"{target}#s02"


@login_required
def export_datafy_supply_view(request):
    """Exporta exatamente o payload DATAFY que a S02 usa nesta selecao."""
    filters = real_sources._construction_filters(request.GET)
    current_payload = real_sources._construction_datafy_snapshot(filters)
    source_mode = current_payload.get("source_mode")
    if source_mode not in {"postgres_live", "postgres_snapshot"}:
        messages.error(request, "DATAFY PostgreSQL indisponivel e sem snapshot para exportar.")
        return redirect(_supply_snapshot_redirect(request))

    exported_at = timezone.now()
    exported_filters = _json_ready(filters)
    exported_payload = _json_ready(current_payload)
    total_materials, total_drawings, material_rows = _supply_snapshot_counts(exported_payload)
    source_created_at = current_payload.get("snapshot_refreshed_at") or exported_at
    payload = {
        "kind": "datafy_supply_snapshot",
        "version": 1,
        "exported_at": exported_at.isoformat(),
        "snapshot": {
            "source_database": current_payload.get("source_database") or settings.DATAFY_DB_NAME,
            "source_host": current_payload.get("source_host") or (
                f"{settings.DATAFY_DB_HOST}:{settings.DATAFY_DB_PORT}"
            ),
            "source_mode": source_mode,
            "filters_hash": supply_filters_hash(filters),
            "filters": exported_filters,
            "payload": exported_payload,
            "total_materials": total_materials,
            "total_drawings": total_drawings,
            "material_rows": material_rows,
            "created_at": (
                source_created_at.isoformat()
                if hasattr(source_created_at, "isoformat")
                else str(source_created_at)
            ),
        },
    }
    content = json.dumps(payload, ensure_ascii=False, default=real_sources.json_default, indent=2)
    timestamp = exported_at.strftime("%Y%m%d-%H%M%S")
    filename = f"datafy_supply_snapshot_{timestamp}.json"
    export_user = getattr(request.user, "_wrapped", request.user)
    if not getattr(export_user, "is_authenticated", False):
        export_user = None
    ExportLog.objects.create(
        user=export_user,
        filename=filename,
        file_format="json",
        module="supply",
        rows=material_rows,
        query_params=request.GET.urlencode()[:1000],
    )
    response = HttpResponse(content, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def import_datafy_supply_view(request):
    """Importa o mesmo JSON exportado pela S02 sem consultar o DATAFY externo."""
    if not getattr(request.user, "is_admin", False):
        raise PermissionDenied("Somente administradores podem importar snapshots DATAFY.")

    target = _supply_snapshot_redirect(request)
    uploaded_file = request.FILES.get("datafy_supply_file")
    if not uploaded_file:
        messages.error(request, "Selecione o JSON exportado da secao Supply antes de importar.")
        return redirect(target)

    try:
        raw = json.loads(uploaded_file.read().decode("utf-8-sig"))
        snapshot_data = raw.get("snapshot") if isinstance(raw, dict) and raw.get("snapshot") else raw
        if not isinstance(snapshot_data, dict):
            raise ValueError("Arquivo sem bloco de snapshot.")
        payload = snapshot_data.get("payload") or {}
        filters = snapshot_data.get("filters") or {}
        if not isinstance(payload, dict):
            raise ValueError("Payload do snapshot invalido.")
        if not isinstance(filters, dict):
            raise ValueError("Filtros do snapshot invalidos.")
        filters = _json_ready(filters)
        payload = _json_ready(payload)
        filters_hash = supply_filters_hash(filters)
        total_materials, total_drawings, material_rows = _supply_snapshot_counts(payload)
        normalized_filters = normalized_supply_snapshot_filters(filters)
        active_snapshot_ids = [
            snapshot.pk
            for snapshot in DatafySupplySnapshot.objects.filter(is_active=True)
            if normalized_supply_snapshot_filters(snapshot.filters) == normalized_filters
        ]
        user = getattr(request.user, "_wrapped", request.user)
        if not getattr(user, "is_authenticated", False):
            user = None
        with transaction.atomic():
            if active_snapshot_ids:
                DatafySupplySnapshot.objects.filter(pk__in=active_snapshot_ids).update(is_active=False)
            snapshot = DatafySupplySnapshot.objects.create(
                source_database=str(snapshot_data.get("source_database") or "DATAFY")[:120],
                source_host=str(snapshot_data.get("source_host") or "")[:120],
                filters_hash=filters_hash,
                filters=filters,
                payload=payload,
                total_materials=total_materials,
                total_drawings=total_drawings,
                material_rows=material_rows,
                refreshed_by=user,
            )
        cache.clear()
    except Exception as exc:
        messages.error(request, f"Falha ao importar snapshot DATAFY Supply: {exc}")
    else:
        messages.success(
            request,
            (
                "Snapshot DATAFY Supply importado: "
                f"{snapshot.total_materials} materiais, "
                f"{snapshot.total_drawings} desenhos e "
                f"{snapshot.material_rows} linhas."
            ),
        )
    return redirect(target)


@login_required
@require_POST
def refresh_datafy_supply_view(request):
    """Atualiza o snapshot da S02 a partir do DATAFY quando solicitado pelo admin."""
    if not getattr(request.user, "is_admin", False):
        raise PermissionDenied("Somente administradores podem atualizar a base de suprimentos.")

    target = reverse("core:home")
    if request.GET.urlencode():
        target = f"{target}?{request.GET.urlencode()}"
    target = f"{target}#s02"

    try:
        filters = real_sources._construction_filters(request.GET)
        snapshot = refresh_supply_snapshot(filters, refreshed_by=request.user)
    except Exception as exc:
        messages.error(
            request,
            (
                "DATAFY database unavailable. The cockpit is still using the last "
                f"snapshot persisted in PostgreSQL. Details: {exc}"
            ),
        )
    else:
        messages.success(
            request,
            (
                "Suprimentos atualizados do DATAFY para a base do sistema: "
                f"{snapshot.total_materials} materiais, "
                f"{snapshot.total_drawings} desenhos e "
                f"{snapshot.material_rows} linhas na tabela."
            ),
        )
    return redirect(target)


@login_required
def model_node_glb(request, node_id: int):
    """Serve uma geometria GLB pequena para destacar um node da hierarquia original."""
    try:
        path = selection_glb_path(node_id)
    except SelectionTooLarge as exc:
        return HttpResponse(str(exc), status=413, content_type="text/plain; charset=utf-8")
    except (FileNotFoundError, ValueError):
        raise Http404("Node 3D nao encontrado")
    return FileResponse(path.open("rb"), content_type="model/gltf-binary")

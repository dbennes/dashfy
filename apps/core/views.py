from __future__ import annotations

import io
import json
from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.permissions import has_module_permission
from apps.core.datafy_supply import refresh_supply_snapshot
from apps.core.engineering_import import import_engineering_status_workbook
from apps.core.model_selection import SelectionTooLarge, selection_glb_path
from apps.core.p6_import import import_p6_curves_workbook
from apps.exports.models import ExportLog
from apps.core import real_sources

from .models import Announcement, EngineeringStatusImport


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
    dashboard_filters = {
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
    if not (getattr(request.user, "is_admin", False) or getattr(request.user, "can_export", False)):
        raise PermissionDenied("Usuario sem permissao de exportacao.")

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
                f"SQLite snapshot. Details: {exc}"
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

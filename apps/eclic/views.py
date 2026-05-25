from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Client
from apps.accounts.permissions import filter_queryset_by_client, module_required
from apps.exports.services import export_queryset_response

from .api_client import EclicAPIError, EclicClient
from .filters import DocumentFilter
from .models import Document, SyncLog
from .services import sync_documents_for_client


def _base_qs(request):
    qs = Document.objects.select_related("client")
    return filter_queryset_by_client(qs, request.user)


@module_required("eclic")
def home(request):
    qs = _base_qs(request)
    f = DocumentFilter(request.GET or None, queryset=qs)
    filtered = f.qs

    kpis = {
        "total": filtered.count(),
        "approved": filtered.filter(status=Document.Status.APPROVED).count(),
        "review": filtered.filter(status=Document.Status.UNDER_REVIEW).count(),
        "draft": filtered.filter(status=Document.Status.DRAFT).count(),
        "obsolete": filtered.filter(status=Document.Status.OBSOLETE).count(),
    }
    categories = (filtered.values("category")
                          .order_by("category")
                          .exclude(category="")
                          .distinct()[:30])
    recent_logs = SyncLog.objects.order_by("-created_at")[:5]
    api_online = EclicClient().ping() if request.GET.get("ping") else None

    return render(request, "eclic/home.html", {
        "filter": f, "filter_form": f.form, "kpis": kpis,
        "categories": categories, "recent_logs": recent_logs,
        "api_online": api_online,
        "export_url": request.path + "?" + request.GET.urlencode(),
    })


@module_required("eclic")
def document_list(request):
    qs = _base_qs(request)
    f = DocumentFilter(request.GET or None, queryset=qs)

    fmt = request.GET.get("format")
    if fmt:
        columns = [
            ("code", "Codigo"), ("title", "Titulo"), ("category", "Categoria"),
            ("document_type", "Tipo"), ("revision", "Revisao"), ("status", "Status"),
            ("issued_at", "Emissao"), ("url", "Link"), ("client__name", "Cliente"),
        ]
        return export_queryset_response(f.qs, columns, "eclic_documentos", fmt)

    page = Paginator(f.qs, 25).get_page(request.GET.get("page"))
    return render(request, "eclic/document_list.html", {
        "filter": f, "filter_form": f.form, "page_obj": page, "paginator": page.paginator,
        "export_url": request.path + "?" + request.GET.urlencode(),
    })


@module_required("eclic")
def document_detail(request, pk: int):
    doc = get_object_or_404(_base_qs(request), pk=pk)
    return render(request, "eclic/document_detail.html", {"doc": doc})


@module_required("eclic", action="edit")
@require_POST
def sync_now(request):
    """Dispara sync sincrono (para volumes pequenos). Use Celery em prod."""
    client_id = request.POST.get("client")
    if not client_id:
        messages.error(request, "Selecione um cliente para sincronizar.")
        return redirect("eclic:home")
    client = get_object_or_404(Client, pk=client_id, is_active=True)
    try:
        log = sync_documents_for_client(client, triggered_by=request.user.username)
        if log.result == SyncLog.Result.SUCCESS:
            messages.success(request,
                f"Sincronizacao concluida: {log.documents_created} criados, "
                f"{log.documents_updated} atualizados.")
        elif log.result == SyncLog.Result.PARTIAL:
            messages.warning(request,
                f"Sincronizacao parcial: {log.documents_errored} com erro.")
        else:
            messages.error(request, f"Falha: {log.error_message[:200]}")
    except EclicAPIError as exc:
        messages.error(request, f"Erro de API: {exc}")
    return redirect("eclic:home")


@module_required("eclic")
def sync_history(request):
    logs = Paginator(SyncLog.objects.select_related("client").order_by("-created_at"),
                     25).get_page(request.GET.get("page"))
    return render(request, "eclic/sync_history.html", {"page_obj": logs,
                                                       "paginator": logs.paginator})

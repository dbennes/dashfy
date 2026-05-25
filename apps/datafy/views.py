from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Sum
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import filter_queryset_by_client, module_required
from apps.core import real_sources
from apps.exports.services import export_queryset_response

from . import charts
from .filters import DataEntryFilter, IndicatorValueFilter
from .models import DataEntry, Indicator, IndicatorValue, Project


def _base_queryset(request):
    qs = DataEntry.objects.select_related("client", "project")
    return filter_queryset_by_client(qs, request.user)


@module_required("datafy")
def home(request):
    source = real_sources.datafy_dashboard()
    documents_source = real_sources.datafy_documents(
        q=request.GET.get("q", "").strip(),
        status=request.GET.get("status", "").strip(),
        discipline=request.GET.get("discipline", "").strip(),
        revision=request.GET.get("revision", "").strip(),
        priority=request.GET.get("priority", "").strip(),
        limit=120,
    )
    charts_payload = source.get("charts", {})

    context = {
        "source": source,
        "documents_source": documents_source,
        "kpis": source.get("kpis", {}),
        "chart_status": json.dumps(charts_payload.get("documents_status", {}), default=real_sources.json_default),
        "chart_disciplines": json.dumps(charts_payload.get("disciplines", {}), default=real_sources.json_default),
        "chart_pos": json.dumps(charts_payload.get("po_status", {}), default=real_sources.json_default),
    }
    return render(request, "datafy/home.html", context)


@module_required("datafy")
def entries_list(request):
    source = real_sources.datafy_documents(
        q=request.GET.get("q", "").strip(),
        status=request.GET.get("status", "").strip(),
        discipline=request.GET.get("discipline", "").strip(),
        revision=request.GET.get("revision", "").strip(),
        priority=request.GET.get("priority", "").strip(),
    )
    paginator = Paginator(source.get("rows", []), 25)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "source": source,
        "page_obj": page,
        "paginator": paginator,
    }
    return render(request, "datafy/entries_list.html", context)


@module_required("datafy")
def indicators(request):
    qs = IndicatorValue.objects.select_related("indicator", "indicator__client")
    qs = filter_queryset_by_client(qs, request.user, field_name="indicator__client")
    f = IndicatorValueFilter(request.GET or None, queryset=qs)

    fmt = request.GET.get("format")
    if fmt:
        columns = [
            ("indicator__code", "Codigo"),
            ("indicator__name", "Indicador"),
            ("indicator__category", "Categoria"),
            ("indicator__unit", "Unidade"),
            ("indicator__target", "Meta"),
            ("period", "Periodo"),
            ("value", "Valor"),
            ("note", "Observacao"),
        ]
        return export_queryset_response(f.qs, columns, "datafy_indicadores", fmt)

    context = {
        "filter": f,
        "filter_form": f.form,
        "values": f.qs.order_by("indicator__code", "-period")[:500],
        "chart_trend": json.dumps(charts.chart_indicator_trend(f.qs)),
        "kpis": {
            "n_indicators": f.qs.values("indicator").distinct().count(),
            "avg_value": f.qs.aggregate(a=Avg("value"))["a"] or 0,
            "n_values": f.qs.count(),
        },
        "export_url": request.path + "?" + request.GET.urlencode(),
    }
    return render(request, "datafy/indicators.html", context)


@module_required("datafy")
def entry_detail(request, pk: int):
    entry = get_object_or_404(_base_queryset(request), pk=pk)
    return render(request, "datafy/entry_detail.html", {"entry": entry})

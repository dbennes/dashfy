from __future__ import annotations

import json
from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.permissions import filter_queryset_by_client, module_required
from apps.core import real_sources
from apps.exports.services import export_queryset_response

from . import charts
from .filters import TaskFilter
from .models import Task


def _base_qs(request):
    qs = Task.objects.select_related("client", "board", "project", "assignee")
    return filter_queryset_by_client(qs, request.user)


@module_required("taskfy")
def home(request):
    source = real_sources.taskfy_dashboard()
    charts_payload = source.get("charts", {})
    context = {
        "source": source,
        "kpis": source.get("kpis", {}),
        "chart_status": json.dumps(charts_payload.get("status", {}), default=real_sources.json_default),
        "chart_disciplines": json.dumps(charts_payload.get("disciplines", {}), default=real_sources.json_default),
        "chart_completion": json.dumps(charts_payload.get("completion", {}), default=real_sources.json_default),
    }
    return render(request, "taskfy/home.html", context)


@module_required("taskfy")
def task_list(request):
    source = real_sources.taskfy_jobcards(
        q=request.GET.get("q", "").strip(),
        status=request.GET.get("status", "").strip(),
        discipline=request.GET.get("discipline", "").strip(),
    )
    page = Paginator(source.get("rows", []), 25).get_page(request.GET.get("page"))
    return render(request, "taskfy/task_list.html", {
        "source": source,
        "page_obj": page,
        "paginator": page.paginator,
    })


@module_required("taskfy")
def kanban(request):
    source = real_sources.taskfy_kanban()
    return render(request, "taskfy/kanban.html", {
        "source": source,
        "columns": source.get("columns", []),
    })


@module_required("taskfy")
def task_detail(request, pk: int):
    task = get_object_or_404(_base_qs(request), pk=pk)
    return render(request, "taskfy/task_detail.html", {"task": task})

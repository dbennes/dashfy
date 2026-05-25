from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import filter_queryset_by_client, module_required
from apps.exports.services import export_queryset_response

from .filters import ScheduleEventFilter
from .models import Schedule, ScheduleEvent


def _base_qs(request):
    qs = ScheduleEvent.objects.select_related("schedule", "schedule__client", "task", "owner")
    return filter_queryset_by_client(qs, request.user, field_name="schedule__client")


@module_required("schedule")
def home(request):
    qs = _base_qs(request)
    f = ScheduleEventFilter(request.GET or None, queryset=qs)
    filtered = f.qs

    kpis = {
        "total": filtered.count(),
        "planned": filtered.filter(status=ScheduleEvent.Status.PLANNED).count(),
        "in_progress": filtered.filter(status=ScheduleEvent.Status.IN_PROGRESS).count(),
        "delayed": filtered.filter(status=ScheduleEvent.Status.DELAYED).count(),
        "completed": filtered.filter(status=ScheduleEvent.Status.COMPLETED).count(),
    }
    schedules = (Schedule.objects.filter(is_active=True)
                                  .select_related("client", "project")
                                  .order_by("-start_date")[:20])

    return render(request, "schedule/home.html", {
        "filter": f, "filter_form": f.form, "kpis": kpis, "schedules": schedules,
        "export_url": request.path + "?" + request.GET.urlencode(),
    })


@module_required("schedule")
def calendar(request):
    """Calendario completo via FullCalendar (eventos via JSON)."""
    f = ScheduleEventFilter(request.GET or None, queryset=_base_qs(request))
    return render(request, "schedule/calendar.html", {
        "filter": f, "filter_form": f.form,
    })


@module_required("schedule")
def calendar_events(request):
    """Endpoint JSON consumido pelo FullCalendar."""
    f = ScheduleEventFilter(request.GET or None, queryset=_base_qs(request))
    events = []
    for ev in f.qs[:1000]:
        events.append({
            "id": ev.pk,
            "title": ev.title,
            "start": ev.start_at.isoformat(),
            "end": ev.end_at.isoformat(),
            "allDay": ev.all_day,
            "backgroundColor": ev.color,
            "borderColor": ev.color,
            "extendedProps": {
                "status": ev.get_status_display(),
                "type": ev.get_event_type_display(),
                "schedule": ev.schedule.name if ev.schedule_id else "",
                "owner": ev.owner.get_full_name() if ev.owner_id else "",
            },
        })
    return JsonResponse(events, safe=False)


@module_required("schedule")
def event_list(request):
    f = ScheduleEventFilter(request.GET or None, queryset=_base_qs(request))

    fmt = request.GET.get("format")
    if fmt:
        columns = [
            ("title", "Titulo"), ("event_type", "Tipo"), ("status", "Status"),
            ("start_at", "Inicio"), ("end_at", "Fim"),
            ("schedule__name", "Cronograma"), ("schedule__client__name", "Cliente"),
            ("owner__username", "Responsavel"), ("location", "Local"),
        ]
        return export_queryset_response(f.qs, columns, "schedule_eventos", fmt)

    page = Paginator(f.qs, 25).get_page(request.GET.get("page"))
    return render(request, "schedule/event_list.html", {
        "filter": f, "filter_form": f.form, "page_obj": page, "paginator": page.paginator,
        "export_url": request.path + "?" + request.GET.urlencode(),
    })


@module_required("schedule")
def event_detail(request, pk: int):
    ev = get_object_or_404(_base_qs(request), pk=pk)
    return render(request, "schedule/event_detail.html", {"ev": ev})

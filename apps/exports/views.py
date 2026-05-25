from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import ExportLog


@login_required
def history(request):
    qs = ExportLog.objects.select_related("user").order_by("-created_at")
    if not request.user.is_admin:
        qs = qs.filter(user=request.user)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "exports/history.html", {"page_obj": page,
                                                    "paginator": page.paginator})

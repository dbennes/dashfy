from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import SavedView


@login_required
def saved_views(request):
    qs = SavedView.objects.filter(Q(user=request.user) | Q(is_shared=True))
    return render(request, "filters/saved_views.html", {"views": qs})


@login_required
@require_POST
def save_view(request):
    name = request.POST.get("name", "").strip()
    module = request.POST.get("module", "").strip()
    path = request.POST.get("path", "").strip()
    qs = request.POST.get("querystring", "").strip()
    if not (name and module and path):
        return HttpResponseBadRequest("Campos obrigatorios: name, module, path")
    sv, created = SavedView.objects.update_or_create(
        user=request.user, name=name,
        defaults={"module": module, "path": path, "querystring": qs,
                  "is_shared": bool(request.POST.get("is_shared"))},
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "id": sv.pk, "created": created})
    messages.success(request, f"View '{name}' salva.")
    return redirect("filters:saved_views")


@login_required
@require_POST
def delete_view(request, pk: int):
    sv = get_object_or_404(SavedView, pk=pk, user=request.user)
    sv.delete()
    messages.info(request, "View removida.")
    return redirect("filters:saved_views")

import hashlib
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from . import rundown_workbook as workbook
from .models import RundownImport

logger = logging.getLogger(__name__)
PREVIEW_SALT = "core.rundown-preview.v1"
MAX_BYTES = 10 * 1024 * 1024


@login_required
@require_GET
def export_rundown(request):
    try:
        content = workbook.export_workbook(workbook.current_state())
    except (DatabaseError, OSError, ValueError):
        logger.exception("Unable to export rundown")
        messages.error(request, "The rundown source is unavailable. Please try again.")
        return redirect(reverse("core:home")+"#s03")
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="DASHFY_Rundown.xlsx"'
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def import_rundown(request):
    if not request.user.is_admin:
        raise PermissionDenied("Only administrators can update rundown data.")
    context, status = {}, 200
    try:
        context["history"] = list(RundownImport.objects.select_related("imported_by")[:10])
        if request.method == "POST":
            action = request.POST.get("action", "preview")
            if action == "apply":
                try:
                    preview = signing.loads(request.POST.get("preview_token", ""), salt=PREVIEW_SALT, max_age=1800)
                except signing.BadSignature as exc:
                    raise ValueError("Preview expired or invalid. Upload the workbook again.") from exc
                if preview["user_id"] != request.user.pk:
                    raise ValueError("Upload and review the workbook using your own account.")
                batch = workbook.apply_import(preview["parsed"], preview["filename"], preview["hash"], request.user)
                messages.success(request, "Rundown updated, including reported progress." if batch else "No changes to apply.")
                return redirect(reverse("core:home")+"#s03")
            if action != "preview":
                raise ValueError("Choose a workbook to preview.")
            upload = request.FILES.get("rundown_file")
            if not upload or not upload.name.lower().endswith(".xlsx"):
                raise ValueError("Choose the exported .xlsx workbook.")
            if upload.size > MAX_BYTES:
                raise ValueError("Maximum file size is 10 MB.")
            content = upload.read(MAX_BYTES+1)
            if len(content) > MAX_BYTES:
                raise ValueError("Maximum file size is 10 MB.")
            parsed = workbook.parse_workbook(content, workbook.current_state())
            context["unchanged"] = not parsed["changes"]
            if parsed["changes"]:
                context.update(preview=parsed, filename=upload.name,
                    preview_token=signing.dumps({"parsed": parsed, "filename": upload.name,
                        "hash": hashlib.sha256(content).hexdigest(), "user_id": request.user.pk}, salt=PREVIEW_SALT, compress=True))
    except (ValueError, KeyError, TypeError) as exc:
        context["error"], status = str(exc), 400
    except (DatabaseError, OSError):
        logger.exception("Unable to import rundown")
        context["error"], status = "Rundown storage is unavailable. No update was applied.", 503
        context["history"] = []
    response = render(request, "core/rundown_import.html", context, status=status)
    response["Cache-Control"] = "no-store"
    return response

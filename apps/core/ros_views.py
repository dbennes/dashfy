"""Export and review manual ROS updates without writing to DATAFY."""
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

from . import ros_workbook
from .models import RosScheduleImport


logger = logging.getLogger(__name__)
PREVIEW_SALT = "core.ros-workbook-preview.v1"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@login_required
@require_GET
def export_ros_view(request):
    try:
        current = ros_workbook.load_current_schedule()
        content = ros_workbook.export_ros_workbook(current)
    except (DatabaseError, OSError, ValueError):
        logger.exception("Unable to export the ROS schedule")
        messages.error(request, "The current ROS schedule is unavailable. Please try again.")
        return redirect(reverse("core:home") + "#s03")
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="DASHFY_ROS.xlsx"'
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def import_ros_view(request):
    if not request.user.is_admin:
        raise PermissionDenied("Only administrators can import the ROS schedule.")
    context = {}
    status = 200
    try:
        current = ros_workbook.load_current_schedule()
        context.update(
            current=current,
            scope_spools=sum(row[3] for row in current["skyline"]["rows"]),
            line_count=len({row[0] for row in current["skyline"]["rows"]}),
            history=list(RosScheduleImport.objects.select_related("imported_by").order_by("-pk")[:10]),
        )
        if request.method == "POST":
            action = request.POST.get("action", "preview")
            if action == "apply":
                try:
                    preview = signing.loads(
                        request.POST.get("preview_token", ""),
                        salt=PREVIEW_SALT,
                        max_age=30 * 60,
                    )
                except signing.BadSignature as exc:
                    raise ValueError("This preview has expired or is invalid. Upload the workbook again.") from exc
                if preview.get("user_id") != request.user.pk:
                    raise ValueError("Upload the workbook using your own account before applying it.")
                batch, created = ros_workbook.apply_ros_import(
                    preview["parsed"],
                    filename=preview["filename"],
                    file_hash=preview["file_hash"],
                    file_size=preview["file_size"],
                    user=request.user,
                )
                if created:
                    messages.success(request, "ROS imported. Skyline and Piping rundown now use the updated schedule.")
                else:
                    messages.info(request, "The workbook matches the current ROS schedule. No changes were needed.")
                return redirect(reverse("core:home") + "#s03")
            if action != "preview":
                raise ValueError("Choose a workbook to preview.")
            upload = request.FILES.get("ros_file")
            if not upload or not upload.name.lower().endswith(".xlsx"):
                raise ValueError("Choose the exported ROS workbook (.xlsx).")
            if upload.size > MAX_UPLOAD_BYTES:
                raise ValueError("The ROS workbook exceeds the 10 MB upload limit.")
            content = upload.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                raise ValueError("The ROS workbook exceeds the 10 MB upload limit.")
            parsed = ros_workbook.parse_ros_workbook(content, current)
            if not parsed["changes"]:
                context["unchanged"] = True
            else:
                preview = {
                    "parsed": parsed,
                    "filename": upload.name,
                    "file_hash": hashlib.sha256(content).hexdigest(),
                    "file_size": len(content),
                    "user_id": request.user.pk,
                }
                context.update(
                    preview=parsed,
                    preview_filename=upload.name,
                    preview_scope=sum(row[3] for row in parsed["skyline"]["rows"]),
                    preview_token=signing.dumps(preview, salt=PREVIEW_SALT, compress=True),
                )
    except (ValueError, KeyError, TypeError) as exc:
        context["error"] = str(exc)
        status = 400
    except (DatabaseError, OSError):
        logger.exception("Unable to process a ROS workbook")
        context["error"] = "The current ROS schedule is unavailable. No changes were applied. Please try again."
        status = 503
    response = render(request, "core/ros_schedule.html", context, status=status)
    response["Cache-Control"] = "no-store"
    return response

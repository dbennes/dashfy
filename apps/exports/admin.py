from django.contrib import admin

from .models import ExportLog


@admin.register(ExportLog)
class ExportLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "filename", "file_format", "module", "rows")
    list_filter = ("file_format", "module")
    search_fields = ("filename", "user__username")
    readonly_fields = [f.name for f in ExportLog._meta.fields]

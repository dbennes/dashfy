from django.contrib import admin

from .models import Document, SyncLog


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "client", "category", "document_type",
                    "revision", "status", "issued_at", "last_synced_at")
    list_filter = ("status", "category", "client")
    search_fields = ("code", "title", "external_id")
    date_hierarchy = "issued_at"
    readonly_fields = ("last_synced_at", "raw_payload")


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "client", "result", "documents_created",
                    "documents_updated", "documents_errored", "duration_seconds")
    list_filter = ("result", "client")
    readonly_fields = [f.name for f in SyncLog._meta.fields]

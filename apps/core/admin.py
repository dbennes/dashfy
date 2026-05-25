from django.contrib import admin

from .models import (
    Announcement,
    DatafySupplySnapshot,
    EngineeringDisciplineStatus,
    EngineeringDocumentStatus,
    EngineeringStatusImport,
    P6CurveImport,
    P6CurvePoint,
    P6ManagementSnapshot,
    P6ProgressRow,
)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "severity", "is_active", "starts_at", "ends_at", "created_at")
    list_filter = ("severity", "is_active")
    search_fields = ("title", "body")


class P6ProgressRowInline(admin.TabularInline):
    model = P6ProgressRow
    extra = 0
    fields = ("row_number", "level", "name", "weight_pct", "planned_pct", "actual_pct")
    readonly_fields = fields
    can_delete = False
    max_num = 0


class P6CurvePointInline(admin.TabularInline):
    model = P6CurvePoint
    extra = 0
    fields = ("sequence", "period", "planned_pct", "actual_pct")
    readonly_fields = fields
    can_delete = False
    max_num = 0


class P6ManagementSnapshotInline(admin.StackedInline):
    model = P6ManagementSnapshot
    extra = 0
    readonly_fields = ("payload", "monthly_point_count", "area_count", "source_sheet", "created_at")
    can_delete = False
    max_num = 0


class EngineeringDisciplineStatusInline(admin.TabularInline):
    model = EngineeringDisciplineStatus
    extra = 0
    fields = (
        "row_number",
        "discipline",
        "not_issued",
        "ifr",
        "ifa",
        "afc_code1",
        "afc_code3",
        "mabu_under_review",
        "total",
    )
    readonly_fields = fields
    can_delete = False
    max_num = 0


class EngineeringDocumentStatusInline(admin.TabularInline):
    model = EngineeringDocumentStatus
    extra = 0
    fields = ("row_number", "document_number", "discipline", "revision", "doc_status", "document_status")
    readonly_fields = fields
    can_delete = False
    max_num = 0


@admin.register(P6CurveImport)
class P6CurveImportAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "is_active",
        "progress_row_count",
        "curve_point_count",
        "executive_row_count",
        "imported_by",
        "created_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("original_filename", "file_hash")
    readonly_fields = (
        "original_filename",
        "file_size",
        "file_hash",
        "imported_by",
        "progress_sheet",
        "curve_sheet",
        "progress_row_count",
        "curve_point_count",
        "executive_row_count",
        "metadata",
        "created_at",
        "updated_at",
    )
    inlines = (P6ManagementSnapshotInline, P6ProgressRowInline, P6CurvePointInline)


@admin.register(EngineeringStatusImport)
class EngineeringStatusImportAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "is_active",
        "document_count",
        "discipline_count",
        "summary_row_count",
        "imported_by",
        "created_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("original_filename", "file_hash")
    readonly_fields = (
        "original_filename",
        "file_size",
        "file_hash",
        "imported_by",
        "summary_sheet",
        "detail_sheet",
        "document_count",
        "discipline_count",
        "summary_row_count",
        "metadata",
        "created_at",
        "updated_at",
    )
    inlines = (EngineeringDisciplineStatusInline, EngineeringDocumentStatusInline)


@admin.register(DatafySupplySnapshot)
class DatafySupplySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "source_database",
        "is_active",
        "total_materials",
        "total_drawings",
        "material_rows",
        "refreshed_by",
        "created_at",
    )
    list_filter = ("is_active", "source_database", "created_at")
    search_fields = ("source_database", "source_host", "filters_hash")
    readonly_fields = (
        "source_database",
        "source_host",
        "filters_hash",
        "filters",
        "payload",
        "total_materials",
        "total_drawings",
        "material_rows",
        "refreshed_by",
        "created_at",
        "updated_at",
    )

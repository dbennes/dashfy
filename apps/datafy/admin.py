from django.contrib import admin

from .models import DataEntry, Dataset, Indicator, IndicatorValue, Project


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "source", "is_active", "updated_at")
    list_filter = ("is_active", "client", "source")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Indicator)
class IndicatorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "client", "unit", "target")
    list_filter = ("category", "client")
    search_fields = ("code", "name")


@admin.register(IndicatorValue)
class IndicatorValueAdmin(admin.ModelAdmin):
    list_display = ("indicator", "period", "value", "note")
    list_filter = ("indicator__category", "indicator__client")
    search_fields = ("indicator__code", "indicator__name")
    date_hierarchy = "period"


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "client", "location", "is_active")
    list_filter = ("is_active", "client")
    search_fields = ("code", "name", "location")


@admin.register(DataEntry)
class DataEntryAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "client", "project", "status",
                    "event_date", "value", "owner")
    list_filter = ("status", "category", "client", "project")
    search_fields = ("reference", "title", "owner")
    date_hierarchy = "event_date"

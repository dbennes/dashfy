from django.contrib import admin

from .models import Schedule, ScheduleEvent


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "project", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "client")
    search_fields = ("name",)


@admin.register(ScheduleEvent)
class ScheduleEventAdmin(admin.ModelAdmin):
    list_display = ("title", "schedule", "event_type", "status", "start_at", "end_at", "owner")
    list_filter = ("event_type", "status", "schedule__client")
    search_fields = ("title", "description", "location")
    date_hierarchy = "start_at"

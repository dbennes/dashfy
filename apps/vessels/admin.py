from django.contrib import admin

from .models import AISListenerState, Vessel, VesselPosition


@admin.register(Vessel)
class VesselAdmin(admin.ModelAdmin):
    list_display = ("name", "mmsi", "imo", "vessel_type", "is_active", "last_seen")
    list_filter = ("is_active",)
    search_fields = ("name", "mmsi", "imo")
    fields = ("name", "mmsi", "imo", "vessel_type", "is_active", "destination", "eta", "draught",
              "last_latitude", "last_longitude", "last_sog", "last_cog", "last_heading",
              "last_navigational_status", "last_seen", "last_static_seen", "last_provider",
              "created_at", "updated_at")
    readonly_fields = fields[5:]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("mmsi",) if obj else ())

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VesselPosition)
class VesselPositionAdmin(admin.ModelAdmin):
    list_display = ("vessel", "timestamp", "latitude", "longitude", "sog", "source", "provider")
    list_filter = ("vessel", "provider")
    date_hierarchy = "timestamp"
    readonly_fields = tuple(field.name for field in VesselPosition._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AISListenerState)
class AISListenerStateAdmin(admin.ModelAdmin):
    list_display = ("provider", "status", "heartbeat_at", "last_message_at", "active_vessel_count")
    readonly_fields = tuple(field.name for field in AISListenerState._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.contrib import admin

from .models import SavedView


@admin.register(SavedView)
class SavedViewAdmin(admin.ModelAdmin):
    list_display = ("name", "module", "user", "is_shared", "is_default", "updated_at")
    list_filter = ("module", "is_shared")
    search_fields = ("name", "path", "querystring")

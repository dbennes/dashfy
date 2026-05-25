from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Client, LoginAudit, ModulePermission, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "client", "is_active", "last_seen")
    list_filter = ("role", "client", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Shell BI", {"fields": ("role", "client", "phone", "avatar", "last_seen")}),
    )


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "cnpj", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "cnpj")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ModulePermission)
class ModulePermissionAdmin(admin.ModelAdmin):
    list_display = ("user", "module", "can_view", "can_export", "can_edit")
    list_filter = ("module", "can_view", "can_export", "can_edit")
    search_fields = ("user__username", "user__email")


@admin.register(LoginAudit)
class LoginAuditAdmin(admin.ModelAdmin):
    list_display = ("username_attempted", "user", "success", "ip_address", "timestamp")
    list_filter = ("success",)
    search_fields = ("username_attempted", "ip_address")
    date_hierarchy = "timestamp"
    readonly_fields = [f.name for f in LoginAudit._meta.fields]

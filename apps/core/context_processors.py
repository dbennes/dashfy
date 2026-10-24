from django.conf import settings

from apps.accounts.permissions import can_view_preparing
from .release_scope import current_release_scope


def branding(request):
    release_scope = getattr(request, "release_scope", current_release_scope())
    scope_params = request.GET.copy()
    scope_params["release_scope"] = release_scope
    return {
        "APP_NAME": settings.APP_NAME,
        "APP_BRAND_MARK": settings.APP_BRAND_MARK,
        "APP_BRAND_PRIMARY": settings.APP_BRAND_PRIMARY,
        "APP_BRAND_SECONDARY": settings.APP_BRAND_SECONDARY,
        "APP_BRAND_DARK": settings.APP_BRAND_DARK,
        "APP_BRAND_ACCENT": settings.APP_BRAND_ACCENT,
        "DASHFY_ENABLE_LEGACY_MODULES": settings.DASHFY_ENABLE_LEGACY_MODULES,
        "can_view_preparing": can_view_preparing(request.user),
        "drawing_release_scope": release_scope,
        "drawing_scope_query": scope_params.urlencode(),
    }

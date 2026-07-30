from django.conf import settings


def branding(request):
    return {
        "APP_NAME": settings.APP_NAME,
        "APP_BRAND_MARK": settings.APP_BRAND_MARK,
        "APP_BRAND_PRIMARY": settings.APP_BRAND_PRIMARY,
        "APP_BRAND_SECONDARY": settings.APP_BRAND_SECONDARY,
        "APP_BRAND_DARK": settings.APP_BRAND_DARK,
        "APP_BRAND_ACCENT": settings.APP_BRAND_ACCENT,
        "DASHFY_ENABLE_LEGACY_MODULES": settings.DASHFY_ENABLE_LEGACY_MODULES,
    }

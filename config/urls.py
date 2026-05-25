from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("", include("apps.core.urls", namespace="core")),
    path("exports/", include("apps.exports.urls", namespace="exports")),
    path("filters/", include("apps.filters.urls", namespace="filters")),
    path("favicon.ico", RedirectView.as_view(url="/static/img/favicon.ico", permanent=True)),
]

if settings.DASHFY_ENABLE_LEGACY_MODULES:
    urlpatterns += [
        path("datafy/", include("apps.datafy.urls", namespace="datafy")),
        path("taskfy/", include("apps.taskfy.urls", namespace="taskfy")),
        path("schedule/", include("apps.schedule.urls", namespace="schedule")),
        path("eclic/", include("apps.eclic.urls", namespace="eclic")),
    ]
else:
    urlpatterns += [
        re_path(
            r"^(?:datafy|taskfy|schedule|eclic)(?:/.*)?$",
            RedirectView.as_view(pattern_name="core:home", permanent=False),
            name="legacy_modules_disabled",
        ),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = f"{settings.APP_NAME} - Administracao"
admin.site.site_title = settings.APP_NAME
admin.site.index_title = "Painel de controle"

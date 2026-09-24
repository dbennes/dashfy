"""
Django settings for DASHFY.

Production-ready settings driven by environment variables (.env).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ------------------------------------------------------------------
# Core
# ------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

APP_NAME = env("APP_NAME", "DASHFY")
APP_BRAND_MARK = env("APP_BRAND_MARK", "D")
APP_BRAND_PRIMARY = env("APP_BRAND_PRIMARY", "#4F46E5")
APP_BRAND_SECONDARY = env("APP_BRAND_SECONDARY", "#06B6D4")
APP_BRAND_DARK = env("APP_BRAND_DARK", "#0F172A")
APP_BRAND_ACCENT = env("APP_BRAND_ACCENT", "#A78BFA")
DASHFY_ENABLE_LEGACY_MODULES = env_bool("DASHFY_ENABLE_LEGACY_MODULES", False)
DASHFY_SHOW_TRACKING = env_bool("DASHFY_SHOW_TRACKING", False)

# ------------------------------------------------------------------
# Real source systems (read-only dashboard integrations)
# ------------------------------------------------------------------
SPDM_BASE_URL = env("SPDM_BASE_URL", "http://127.0.0.1:8000")

DATAFY_DB_NAME = env("DATAFY_DB_NAME", "DATAFY")
DATAFY_DB_USER = env("DATAFY_DB_USER", env("TASKFY_DB_USER", "postgres"))
DATAFY_DB_PASSWORD = env("DATAFY_DB_PASSWORD", env("TASKFY_DB_PASSWORD", ""))
DATAFY_DB_HOST = env("DATAFY_DB_HOST", env("TASKFY_DB_HOST", "localhost"))
DATAFY_DB_PORT = env("DATAFY_DB_PORT", env("TASKFY_DB_PORT", "5432"))
DATAFY_BASE_URL = env("DATAFY_BASE_URL", SPDM_BASE_URL)

TASKFY_DB_NAME = env("TASKFY_DB_NAME", "taskfy")
TASKFY_DB_USER = env("TASKFY_DB_USER", "postgres")
TASKFY_DB_PASSWORD = env("TASKFY_DB_PASSWORD", "")
TASKFY_DB_HOST = env("TASKFY_DB_HOST", "localhost")
TASKFY_DB_PORT = env("TASKFY_DB_PORT", "5432")
TASKFY_BASE_URL = env("TASKFY_BASE_URL", "http://127.0.0.1:8080")

P6_CURVES_PATH = env(
    "P6_CURVES_PATH",
    str(Path.home() / "Downloads" / "Annex III -CURVES BN-EPC 1-WEEKLY-NW-W102.xlsx"),
)

# ------------------------------------------------------------------
# Apps
# ------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "django_tables2",
    "crispy_forms",
    "crispy_bootstrap5",
    "import_export",
    "django_extensions",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.core",
    "apps.filters",
    "apps.exports",
    "apps.datafy",
    "apps.taskfy",
    "apps.schedule",
    "apps.eclic",
    "apps.vessels",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ------------------------------------------------------------------
# Middleware
# ------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.branding",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------
def _db_config(
    prefix: str,
    *,
    default_name: str,
    fallback_prefix: str | None = None,
) -> dict:
    def value(suffix: str, default: str) -> str:
        if fallback_prefix:
            default = env(f"{fallback_prefix}_{suffix}", default)
        return env(f"{prefix}_{suffix}", default)

    return {
        "ENGINE": "django.db.backends.postgresql",
        # The database name never inherits from an integration. This prevents
        # migrations from targeting DATAFY/Taskfy when DB_NAME is omitted.
        "NAME": env(f"{prefix}_NAME", default_name),
        "USER": value("USER", "postgres"),
        "PASSWORD": value("PASSWORD", ""),
        "HOST": value("HOST", "localhost"),
        "PORT": value("PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }


DATABASES = {
    "default": _db_config(
        "DB",
        default_name="DASHFY",
        fallback_prefix=env("DB_CREDENTIALS_PREFIX", "").strip() or None,
    ),
    "business": _db_config(
        "BUSINESS_DB",
        default_name="DATAFY",
        fallback_prefix="DATAFY_DB",
    ),
}

DATABASE_ROUTERS = ["apps.core.db_router.BusinessRouter"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

LOGIN_EXEMPT_URLS = [
    r"^accounts/login/?$",
    r"^accounts/logout/?$",
    r"^accounts/password_reset/.*$",
    r"^static/.*$",
    r"^media/.*$",
    r"^favicon\.ico$",
    r"^admin/login/?$",
    # A API de embarcacoes responde 403 em JSON; redirecionar para o HTML de
    # login quebraria o fetch do cockpit e nao revelaria nada a mais.
    r"^vessels/api/.*$",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_AGE = 60 * 60 * 8  # 8h
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

# ------------------------------------------------------------------
# i18n
# ------------------------------------------------------------------
LANGUAGE_CODE = env("DJANGO_LANGUAGE_CODE", "pt-br")
TIME_ZONE = env("DJANGO_TIME_ZONE", "America/Sao_Paulo")
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------
# Static / media
# ------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if not DEBUG:
    STATICFILES_STORAGE = "config.static_storage.DashboardStaticStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ------------------------------------------------------------------
# Crispy
# ------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ------------------------------------------------------------------
# REST Framework
# ------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ------------------------------------------------------------------
# Cache + Celery
# ------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
DASHFY_SOURCE_CACHE_SECONDS = max(0, int(env("DASHFY_SOURCE_CACHE_SECONDS", "45")))

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dashfy-default",
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# ------------------------------------------------------------------
# ECLIC API
# ------------------------------------------------------------------
ECLIC_API_BASE_URL = env("ECLIC_API_BASE_URL", "")
ECLIC_API_KEY = env("ECLIC_API_KEY", "")
ECLIC_API_USER = env("ECLIC_API_USER", "")
ECLIC_API_PASSWORD = env("ECLIC_API_PASSWORD", "")
ECLIC_API_TIMEOUT = int(env("ECLIC_API_TIMEOUT", "30"))
ECLIC_API_CLIENT_ID = int(env("ECLIC_API_CLIENT_ID", "0") or 0)
ECLIC_API_PROJECT_ID = int(env("ECLIC_API_PROJECT_ID", "0") or 0)

# ------------------------------------------------------------------
# Email
# ------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@dashfy.local")

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "dashfy.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "INFO"},
        "dashfy": {"handlers": ["console", "file"], "level": "INFO"},
        "apps": {"handlers": ["console", "file"], "level": "INFO"},
    },
}

# ------------------------------------------------------------------
# Security (prod)
# ------------------------------------------------------------------
if not DEBUG:
    # Direct Waitress deployments can run over HTTP. Enable these options only
    # after TLS is terminated by a trusted reverse proxy.
    if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", False)
    SECURE_HSTS_SECONDS = int(env("DJANGO_SECURE_HSTS_SECONDS", "0") or 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
        False,
    )
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"


# ------------------------------------------------------------------
# Rastreamento de embarcacoes (AIS)
# ------------------------------------------------------------------
# Chave privada do provedor, usada somente pelo coletor no servidor. O browser
# recebe apenas um indicador de "configurado" e o status sanitizado da conexao.
AISSTREAM_API_KEY = env("AISSTREAM_API_KEY", "")
AISSTREAM_BOUNDING_BOXES = [[[-90, -180], [90, 180]]]

# Cadencia de retencao de posicoes recebidas.
AIS_POSITION_INTERVAL_SECONDS = int(env("AIS_POSITION_INTERVAL_SECONDS", "180") or 180)
AIS_POSITION_MIN_SECONDS = int(env("AIS_POSITION_MIN_SECONDS", "10") or 10)
AIS_POSITION_DISTANCE_METERS = int(env("AIS_POSITION_DISTANCE_METERS", "250") or 250)
AIS_POSITION_COURSE_DEGREES = int(env("AIS_POSITION_COURSE_DEGREES", "15") or 15)
AIS_SUBSCRIPTION_REFRESH_SECONDS = int(env("AIS_SUBSCRIPTION_REFRESH_SECONDS", "30") or 30)

# Frescor do sinal e saude do coletor.
AIS_RECENT_SECONDS = int(env("AIS_RECENT_SECONDS", "600") or 600)
AIS_STALE_SECONDS = int(env("AIS_STALE_SECONDS", "3600") or 3600)
AIS_HEARTBEAT_TIMEOUT_SECONDS = int(env("AIS_HEARTBEAT_TIMEOUT_SECONDS", "120") or 120)

# Limites da frota e do historico exposto pela API.
AIS_MAX_ACTIVE_VESSELS = int(env("AIS_MAX_ACTIVE_VESSELS", "200") or 200)
AIS_MAX_TRACK_POINTS = int(env("AIS_MAX_TRACK_POINTS", "5000") or 5000)
AIS_POLL_SECONDS = int(env("AIS_POLL_SECONDS", "20") or 20)

# Mapa. Um provedor diferente pode ser usado trocando a URL e a atribuicao; uma
# atribuicao personalizada e renderizada como texto puro, nunca como markup.
AIS_MAP_TILE_URL = env(
    "AIS_MAP_TILE_URL",
    "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
)
AIS_MAP_ATTRIBUTION = env("AIS_MAP_ATTRIBUTION", "Esri, HERE, Garmin, \u00a9 OpenStreetMap contributors")
# Os nomes de lugares vem numa camada transparente por cima, para que a
# recoloracao de mar e terra nao desbote o texto. Vazio desliga os rotulos.
AIS_MAP_LABELS_URL = env(
    "AIS_MAP_LABELS_URL",
    "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
)

# Modelo 3D do dossie. Aceita .glb/.gltf (menor), .fbx ou .obj. Vazio mantem a
# projecao esquematica embutida.
AIS_VESSEL_MODEL_URL = env("AIS_VESSEL_MODEL_URL", "/static/models/vessel-hq.glb")

# Fixed operational area anchored to the position the user identified as AVEON
# JETTY PH on 2026-09-16. This is not a surveyed port boundary, and the centre
# must never follow subsequent vessel positions.
AIS_PORT_GEOFENCES = [
    {"id": "aveon-jetty-ph", "name": "AVEON JETTY PH", "latitude": 4.7942467,
     "longitude": 6.9417582, "radius_m": 3000},
    {"id": "bonga-north", "name": "BONGA NORTH", "latitude": 4.5575266,
     "longitude": 4.6164432, "radius_m": 3000},
]

# Regular supply shuttle confirmed by the user. The second endpoint is the
# configured outbound target when no departure has yet been observed.
AIS_VESSEL_SHUTTLE_ROUTES = {
    "636023616": ["aveon-jetty-ph", "bonga-north"],
}

"""
Django settings for Shell BI project.

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
        default_name="shellbi",
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
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

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

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "shellbi-default",
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
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@shellbi.local")

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
            "filename": LOG_DIR / "shellbi.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "INFO"},
        "shellbi": {"handlers": ["console", "file"], "level": "INFO"},
        "apps": {"handlers": ["console", "file"], "level": "INFO"},
    },
}

# ------------------------------------------------------------------
# Security (prod)
# ------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

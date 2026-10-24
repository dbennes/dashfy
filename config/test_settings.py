"""Disposable tests: no operational Django or integration database access."""
from .settings import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    "business": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# Integration SELECTs must use fixtures/mocks. Unmocked reads fail immediately
# against an unused local port instead of reading the live source systems.
DATAFY_DB_HOST = TASKFY_DB_HOST = "127.0.0.1"
DATAFY_DB_PORT = TASKFY_DB_PORT = "1"
DATAFY_DB_NAME = TASKFY_DB_NAME = "dashfy_test_sources_only"
DATAFY_DB_PASSWORD = TASKFY_DB_PASSWORD = ""

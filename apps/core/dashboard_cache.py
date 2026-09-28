"""Short-lived cache for project-wide sources, never user/permission payloads."""
from functools import wraps
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
from threading import RLock

from django.conf import settings
from django.core.cache import cache as django_cache
from django.utils import timezone

# Bounded locks coalesce concurrent first loads in each Waitress process.
_LOCKS = [RLock() for _ in range(32)]
_FRESH = ContextVar("dashboard_fresh_sources", default=False)


def fresh_sources_requested():
    return _FRESH.get()


@contextmanager
def fresh_sources():
    token = _FRESH.set(True)
    try:
        yield
    finally:
        _FRESH.reset(token)


class SourceCache:
    def get(self, key, default=None, **kwargs):
        return default if _FRESH.get() else django_cache.get(key, default, **kwargs)

    def set(self, *args, **kwargs):
        if not _FRESH.get():
            return django_cache.set(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(django_cache, name)


cache = SourceCache()


def cached_dashboard_source(name):
    def decorate(loader):
        @wraps(loader)
        def wrapped(*args, **kwargs):
            ttl = getattr(settings, "DASHFY_SOURCE_CACHE_SECONDS", 45)
            if ttl <= 0 or _FRESH.get():
                return loader(*args, **kwargs)
            identity = json.dumps([name, timezone.localdate().isoformat(), args, kwargs],
                                  sort_keys=True, default=str)
            digest = sha256(identity.encode()).hexdigest()
            key = f"dashboard-source:v1:{digest}"
            value = cache.get(key)
            if value is not None:
                return value
            with _LOCKS[int(digest[:8], 16) % len(_LOCKS)]:
                value = cache.get(key)
                if value is None:
                    # Exceptions propagate to the source's existing safe wrapper;
                    # a temporary outage must not become a cached success.
                    value = loader(*args, **kwargs)
                    cache.set(key, value, timeout=ttl)
                return value
        return wrapped
    return decorate

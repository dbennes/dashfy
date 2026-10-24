"""Request-local drawing selection shared by DATAFY readers and caches."""
from contextlib import contextmanager
from contextvars import ContextVar
import re


RELEASE_SCOPES = ("official", "preparing", "all")
_SCOPE = ContextVar("dashfy_drawing_release_scope", default="official")


def current_release_scope():
    return _SCOPE.get()


@contextmanager
def release_scope_context(scope):
    if scope not in RELEASE_SCOPES:
        raise ValueError("Invalid drawing release scope.")
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def document_scope_sql(alias="d"):
    if alias and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("Invalid document alias.")
    field = f"{alias}.release_status" if alias else "release_status"
    scope = current_release_scope()
    if scope == "all":
        return f"{field} in ('official', 'preparing')"
    return f"{field} = '{scope}'"

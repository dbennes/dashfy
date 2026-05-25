"""Helpers para verificar permissoes de modulo nas views."""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import ModulePermission, User


def has_module_permission(user: User, module: str, action: str = "view") -> bool:
    if not user.is_authenticated:
        return False
    if user.is_admin:
        return True
    field = f"can_{action}"
    return ModulePermission.objects.filter(
        user=user, module=module, **{field: True}
    ).exists()


def module_required(module: str, action: str = "view"):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not has_module_permission(request.user, module, action):
                raise PermissionDenied(
                    f"Voce nao tem permissao para {action} no modulo {module}."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def filter_queryset_by_client(qs, user: User, field_name: str = "client"):
    """Aplica row-level filtering se o usuario tiver Cliente vinculado."""
    if user.is_admin or user.client_id is None:
        return qs
    return qs.filter(**{field_name: user.client_id})

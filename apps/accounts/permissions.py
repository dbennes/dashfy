"""Helpers para verificar permissoes de modulo nas views."""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import ModulePermission, User


def can_view_preparing(user) -> bool:
    """Preparing access follows an explicit profile, independently of modules.

    Legacy analysts and clients retain their existing Official-only scope.
    Staff status permits Django administration but does not grant this scope.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "role", None) in {
            User.Role.ADMIN, User.Role.PLANNING, User.Role.SUPPLY,
        }
    )


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

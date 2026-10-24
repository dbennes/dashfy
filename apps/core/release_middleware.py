"""Resolve the permitted scope before any dashboard source is queried."""
from django.utils.cache import patch_cache_control, patch_vary_headers

from apps.accounts.permissions import can_view_preparing
from .release_scope import RELEASE_SCOPES, release_scope_context


SESSION_KEY = "dashfy_release_scope"


class DrawingReleaseScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        scope = request.GET.get("release_scope")
        if scope is None:
            scope = request.POST.get("release_scope", request.session.get(SESSION_KEY, "official"))
        if scope not in RELEASE_SCOPES or not can_view_preparing(request.user):
            scope = "official"
        request.release_scope = scope
        if request.user.is_authenticated and request.session.get(SESSION_KEY) != scope:
            request.session[SESSION_KEY] = scope
        with release_scope_context(scope):
            response = self.get_response(request)
        if request.user.is_authenticated:
            # A page or API response must never survive a role/scope change in
            # a shared browser or be reused by a shared proxy cache.
            patch_cache_control(response, private=True, no_store=True)
            patch_vary_headers(response, ("Cookie",))
            response["X-Drawing-Release-Scope"] = scope
        return response

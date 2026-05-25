from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url
from django.utils import timezone


class LoginRequiredMiddleware:
    """Force login for every URL except the ones in LOGIN_EXEMPT_URLS."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        self.exempt = [re.compile(p) for p in getattr(settings, "LOGIN_EXEMPT_URLS", [])]

    def __call__(self, request):
        path = request.path_info.lstrip("/")
        if not request.user.is_authenticated and not any(p.match(path) for p in self.exempt):
            login_url = resolve_url(settings.LOGIN_URL)
            target = f"{login_url}?{urlencode({'next': request.get_full_path()})}"
            return HttpResponseRedirect(target)
        if request.user.is_authenticated:
            now = timezone.now()
            get_user_model().objects.filter(pk=request.user.pk).update(last_seen=now)
        return self.get_response(request)

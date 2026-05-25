from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import LoginForm, ProfileForm
from .models import LoginAudit


def _client_ip(request: HttpRequest) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class ShellLoginView(LoginView):
    form_class = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        LoginAudit.objects.create(
            user=form.get_user(),
            username_attempted=form.cleaned_data.get("username", ""),
            success=True,
            ip_address=_client_ip(self.request),
            user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:1000],
        )
        if not form.cleaned_data.get("remember"):
            self.request.session.set_expiry(0)
        self.request.session["show_login_boot"] = True
        messages.success(self.request, "Welcome back.")
        return response

    def form_invalid(self, form):
        LoginAudit.objects.create(
            username_attempted=form.data.get("username", ""),
            success=False,
            ip_address=_client_ip(self.request),
            user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:1000],
        )
        return super().form_invalid(form)


class ShellLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil atualizado.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form})

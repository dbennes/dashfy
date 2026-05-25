from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class Client(models.Model):
    """Tenant/cliente final. Usado para filtrar dados (row-level)."""

    name = models.CharField(_("Nome"), max_length=120, unique=True)
    slug = models.SlugField(_("Slug"), max_length=120, unique=True)
    cnpj = models.CharField(_("CNPJ"), max_length=18, blank=True)
    logo = models.ImageField(_("Logo"), upload_to="clients/", blank=True, null=True)
    primary_color = models.CharField(_("Cor primaria"), max_length=7, default="#FBCE07")
    is_active = models.BooleanField(_("Ativo"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Cliente")
        verbose_name_plural = _("Clientes")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Usuario do sistema. Pode pertencer a um Cliente (multi-tenant)."""

    class Role(models.TextChoices):
        ADMIN = "admin", _("Administrador")
        ANALYST = "analyst", _("Analista")
        VIEWER = "viewer", _("Visualizador")
        CLIENT = "client", _("Cliente")

    email = models.EmailField(_("Email"), blank=True, null=True)
    role = models.CharField(
        _("Perfil"), max_length=20, choices=Role.choices, default=Role.VIEWER
    )
    client = models.ForeignKey(
        Client,
        verbose_name=_("Cliente"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        help_text=_("Cliente ao qual este usuario pertence (row-level filter)."),
    )
    phone = models.CharField(_("Telefone"), max_length=20, blank=True)
    avatar = models.ImageField(_("Avatar"), upload_to="avatars/", blank=True, null=True)
    last_seen = models.DateTimeField(_("Ultimo acesso"), null=True, blank=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("Usuario")
        verbose_name_plural = _("Usuarios")
        ordering = ["username"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def can_export(self) -> bool:
        return self.role in {self.Role.ADMIN, self.Role.ANALYST, self.Role.CLIENT}


class ModulePermission(models.Model):
    """Permissoes finas por modulo (Datafy/Taskfy/Schedule/Eclic) por usuario."""

    class Module(models.TextChoices):
        DATAFY = "datafy", "Datafy"
        TASKFY = "taskfy", "Taskfy"
        SCHEDULE = "schedule", "Schedule"
        ECLIC = "eclic", "ECLIC"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="module_permissions"
    )
    module = models.CharField(max_length=20, choices=Module.choices)
    can_view = models.BooleanField(default=True)
    can_export = models.BooleanField(default=True)
    can_edit = models.BooleanField(default=False)

    class Meta:
        unique_together = ("user", "module")
        verbose_name = _("Permissao de modulo")
        verbose_name_plural = _("Permissoes de modulos")

    def __str__(self) -> str:
        return f"{self.user} - {self.get_module_display()}"


class LoginAudit(models.Model):
    """Auditoria de logins (quem entrou e quando)."""

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="login_audits"
    )
    username_attempted = models.CharField(max_length=150)
    success = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = _("Auditoria de login")
        verbose_name_plural = _("Auditorias de login")

    def __str__(self) -> str:
        status = "OK" if self.success else "FALHA"
        return f"{self.username_attempted} [{status}] {self.timestamp:%Y-%m-%d %H:%M}"

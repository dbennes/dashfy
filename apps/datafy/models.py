"""
Modelos do modulo Datafy.

Convivem aqui:
- Dataset / DatasetRecord: armazenamento generico de KPIs/registros operacionais
  controlados pelo proprio BI (caso voce queira ingerir dados via upload/API).
- Tabelas externas: se voce ja tem tabelas no PostgreSQL do Datafy, basta criar
  uma classe Meta com managed = False e db_table = 'sua_tabela'.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Client
from apps.core.models import TimestampedModel


class Dataset(TimestampedModel):
    """Conjunto de dados ingerido pelo BI (logico, multi-cliente)."""

    name = models.CharField(_("Nome"), max_length=120)
    slug = models.SlugField(_("Slug"), max_length=140, unique=True)
    description = models.TextField(_("Descricao"), blank=True)
    client = models.ForeignKey(
        Client, verbose_name=_("Cliente"), on_delete=models.CASCADE, related_name="datafy_datasets"
    )
    source = models.CharField(_("Origem"), max_length=120, blank=True,
                              help_text=_("Ex: upload manual, API XPTO, integracao SAP..."))
    is_active = models.BooleanField(_("Ativo"), default=True)

    class Meta:
        verbose_name = _("Dataset")
        verbose_name_plural = _("Datasets")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.client})"


class Indicator(TimestampedModel):
    """Indicador (KPI) registrado para um cliente."""

    class Category(models.TextChoices):
        PERFORMANCE = "performance", "Performance"
        FINANCIAL = "financial", "Financeiro"
        SAFETY = "safety", "Seguranca"
        QUALITY = "quality", "Qualidade"
        OPERATIONS = "operations", "Operacoes"
        OTHER = "other", "Outro"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="indicators"
    )
    code = models.CharField(_("Codigo"), max_length=40, db_index=True)
    name = models.CharField(_("Nome"), max_length=160)
    category = models.CharField(_("Categoria"), max_length=30,
                                choices=Category.choices, default=Category.PERFORMANCE)
    unit = models.CharField(_("Unidade"), max_length=20, blank=True)
    target = models.DecimalField(_("Meta"), max_digits=14, decimal_places=4,
                                 null=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ("client", "code")
        verbose_name = _("Indicador")
        verbose_name_plural = _("Indicadores")
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class IndicatorValue(TimestampedModel):
    """Valor mensurado de um indicador em um momento."""

    indicator = models.ForeignKey(
        Indicator, on_delete=models.CASCADE, related_name="values"
    )
    period = models.DateField(_("Periodo"), db_index=True)
    value = models.DecimalField(_("Valor"), max_digits=14, decimal_places=4)
    note = models.CharField(_("Observacao"), max_length=255, blank=True)

    class Meta:
        unique_together = ("indicator", "period")
        ordering = ["-period"]
        verbose_name = _("Valor de indicador")
        verbose_name_plural = _("Valores de indicadores")

    def __str__(self) -> str:
        return f"{self.indicator.code} @ {self.period}: {self.value}"


class Project(TimestampedModel):
    """Projetos / Obras (usado pelo Datafy para classificar registros)."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="projects")
    code = models.CharField(max_length=40, db_index=True)
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("client", "code")
        ordering = ["code"]
        verbose_name = _("Projeto")
        verbose_name_plural = _("Projetos")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class DataEntry(TimestampedModel):
    """Registro operacional generico (substitui linhas do Datafy externo)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        OPEN = "open", "Aberto"
        IN_PROGRESS = "in_progress", "Em andamento"
        DONE = "done", "Concluido"
        BLOCKED = "blocked", "Bloqueado"
        CANCELLED = "cancelled", "Cancelado"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="data_entries")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="data_entries")
    reference = models.CharField(_("Referencia"), max_length=80, db_index=True)
    title = models.CharField(_("Titulo"), max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(_("Categoria"), max_length=60, blank=True, db_index=True)
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices,
                              default=Status.OPEN, db_index=True)
    quantity = models.DecimalField(_("Quantidade"), max_digits=14, decimal_places=4,
                                   null=True, blank=True)
    value = models.DecimalField(_("Valor"), max_digits=14, decimal_places=2,
                                null=True, blank=True)
    event_date = models.DateField(_("Data do evento"), db_index=True)
    owner = models.CharField(_("Responsavel"), max_length=120, blank=True)

    class Meta:
        ordering = ["-event_date", "-id"]
        verbose_name = _("Registro Datafy")
        verbose_name_plural = _("Registros Datafy")
        indexes = [
            models.Index(fields=["client", "event_date"]),
            models.Index(fields=["status", "event_date"]),
        ]

    def __str__(self) -> str:
        return f"[{self.reference}] {self.title}"

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Client
from apps.core.models import TimestampedModel


class Document(TimestampedModel):
    """Documento ECLIC (sincronizado via API)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        UNDER_REVIEW = "review", "Em revisao"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Rejeitado"
        OBSOLETE = "obsolete", "Obsoleto"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="eclic_documents")
    external_id = models.CharField(_("ID externo (ECLIC)"), max_length=80, db_index=True)
    code = models.CharField(_("Codigo"), max_length=80, db_index=True)
    title = models.CharField(_("Titulo"), max_length=300)
    description = models.TextField(blank=True)
    category = models.CharField(_("Categoria"), max_length=120, blank=True, db_index=True)
    document_type = models.CharField(_("Tipo"), max_length=80, blank=True)
    revision = models.CharField(_("Revisao"), max_length=20, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices,
                              default=Status.DRAFT, db_index=True)
    url = models.URLField(_("Link no ECLIC"), blank=True)
    file_size = models.BigIntegerField(_("Tamanho (bytes)"), null=True, blank=True)
    issued_at = models.DateField(_("Data de emissao"), null=True, blank=True)
    last_synced_at = models.DateTimeField(_("Ultima sincronizacao"), null=True, blank=True)
    raw_payload = models.JSONField(_("Payload bruto"), null=True, blank=True)

    class Meta:
        unique_together = ("client", "external_id")
        ordering = ["-issued_at", "code"]
        verbose_name = _("Documento ECLIC")
        verbose_name_plural = _("Documentos ECLIC")
        indexes = [
            models.Index(fields=["client", "category"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"[{self.code}] {self.title}"


class SyncLog(TimestampedModel):
    class Result(models.TextChoices):
        SUCCESS = "success", "Sucesso"
        PARTIAL = "partial", "Parcial"
        FAILED = "failed", "Falha"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="eclic_syncs",
                               null=True, blank=True)
    triggered_by = models.CharField(max_length=120, blank=True)
    result = models.CharField(max_length=20, choices=Result.choices)
    documents_created = models.IntegerField(default=0)
    documents_updated = models.IntegerField(default=0)
    documents_errored = models.IntegerField(default=0)
    duration_seconds = models.FloatField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Log de sincronizacao")
        verbose_name_plural = _("Logs de sincronizacao")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_result_display()}"

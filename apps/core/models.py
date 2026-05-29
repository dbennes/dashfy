from django.conf import settings
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Announcement(TimestampedModel):
    """Avisos exibidos na home/dashboard."""

    title = models.CharField(max_length=200)
    body = models.TextField()
    severity = models.CharField(
        max_length=20,
        choices=[
            ("info", "Info"),
            ("success", "Sucesso"),
            ("warning", "Aviso"),
            ("danger", "Critico"),
        ],
        default="info",
    )
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class P6CurveImport(TimestampedModel):
    """Lote importado do Annex III de curvas P6."""

    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    file_hash = models.CharField(max_length=64, db_index=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="p6_curve_imports",
    )
    progress_sheet = models.CharField(max_length=120, default="Progress PMS (%)")
    curve_sheet = models.CharField(max_length=120, default="DB (%)")
    progress_row_count = models.PositiveIntegerField(default=0)
    curve_point_count = models.PositiveIntegerField(default=0)
    executive_row_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["file_hash"]),
        ]
        verbose_name = "Importacao de curva P6"
        verbose_name_plural = "Importacoes de curvas P6"

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.created_at:%d/%m/%Y %H:%M})"


class P6ProgressRow(models.Model):
    """Linha normalizada da aba Progress PMS (%)."""

    import_batch = models.ForeignKey(
        P6CurveImport,
        on_delete=models.CASCADE,
        related_name="progress_rows",
    )
    row_number = models.PositiveIntegerField()
    level = models.PositiveSmallIntegerField(db_index=True)
    name = models.CharField(max_length=255)
    weight_pct = models.FloatField(default=0)
    baseline_pct = models.FloatField(default=0)
    planned_pct = models.FloatField(default=0)
    actual_pct = models.FloatField(default=0)

    class Meta:
        ordering = ["row_number"]
        indexes = [
            models.Index(fields=["import_batch", "level"]),
            models.Index(fields=["import_batch", "row_number"]),
        ]
        unique_together = ("import_batch", "row_number")
        verbose_name = "Linha PMS P6"
        verbose_name_plural = "Linhas PMS P6"

    def __str__(self) -> str:
        return f"L{self.level} - {self.name}"


class P6CurvePoint(models.Model):
    """Ponto semanal normalizado da aba DB (%)."""

    import_batch = models.ForeignKey(
        P6CurveImport,
        on_delete=models.CASCADE,
        related_name="curve_points",
    )
    sequence = models.PositiveIntegerField()
    period = models.DateField(db_index=True)
    planned_pct = models.FloatField(default=0)
    actual_pct = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["sequence", "period"]
        indexes = [
            models.Index(fields=["import_batch", "period"]),
        ]
        unique_together = ("import_batch", "period")
        verbose_name = "Ponto de curva P6"
        verbose_name_plural = "Pontos de curva P6"

    def __str__(self) -> str:
        return f"{self.period:%d/%m/%Y} - {self.planned_pct:.2f}%"


class P6ManagementSnapshot(models.Model):
    """Payload gerencial S03 extraido do Annex III e salvo no SQLite."""

    import_batch = models.OneToOneField(
        P6CurveImport,
        on_delete=models.CASCADE,
        related_name="management_snapshot",
    )
    payload = models.JSONField(default=dict, blank=True)
    monthly_point_count = models.PositiveIntegerField(default=0)
    area_count = models.PositiveIntegerField(default=0)
    source_sheet = models.CharField(max_length=120, default="DB BLPMSACT")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Snapshot gerencial P6"
        verbose_name_plural = "Snapshots gerenciais P6"

    def __str__(self) -> str:
        return f"S03 {self.import_batch.original_filename}"


class EngineeringStatusImport(TimestampedModel):
    """Lote DED importado do XLSX de status de engenharia."""

    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    file_hash = models.CharField(max_length=64, db_index=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="engineering_status_imports",
    )
    summary_sheet = models.CharField(max_length=120, default="Sheet2")
    detail_sheet = models.CharField(max_length=120, default="Sheet1")
    document_count = models.PositiveIntegerField(default=0)
    discipline_count = models.PositiveIntegerField(default=0)
    summary_row_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["file_hash"]),
        ]
        verbose_name = "Importacao DED engenharia"
        verbose_name_plural = "Importacoes DED engenharia"

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.created_at:%d/%m/%Y %H:%M})"


class EngineeringDisciplineStatus(models.Model):
    """Resumo por disciplina da aba Sheet2 do DED."""

    import_batch = models.ForeignKey(
        EngineeringStatusImport,
        on_delete=models.CASCADE,
        related_name="discipline_summaries",
    )
    row_number = models.PositiveIntegerField()
    discipline = models.CharField(max_length=160, db_index=True)
    not_issued = models.PositiveIntegerField(default=0)
    ifr = models.PositiveIntegerField(default=0)
    ifa = models.PositiveIntegerField(default=0)
    afc_code1 = models.PositiveIntegerField(default=0)
    afc_code3 = models.PositiveIntegerField(default=0)
    mabu_under_review = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["row_number", "discipline"]
        indexes = [
            models.Index(fields=["import_batch", "discipline"]),
        ]
        unique_together = ("import_batch", "row_number")
        verbose_name = "Resumo DED por disciplina"
        verbose_name_plural = "Resumos DED por disciplina"

    def __str__(self) -> str:
        return f"{self.discipline} - {self.total}"


class EngineeringDocumentStatus(models.Model):
    """Linha detalhada de desenho/documento da aba Sheet1 do DED."""

    import_batch = models.ForeignKey(
        EngineeringStatusImport,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    row_number = models.PositiveIntegerField()
    document_number = models.CharField(max_length=180, db_index=True)
    title = models.CharField(max_length=600, blank=True)
    discipline = models.CharField(max_length=160, db_index=True)
    revision = models.CharField(max_length=40, blank=True, db_index=True)
    revision_family = models.CharField(max_length=8, blank=True, db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=0)
    doc_status = models.CharField(max_length=120, blank=True, db_index=True)
    doc_status_group = models.CharField(max_length=40, blank=True, db_index=True)
    afc_code = models.CharField(max_length=20, blank=True, db_index=True)
    document_status = models.CharField(max_length=120, blank=True, db_index=True)
    workflow_start = models.DateField(null=True, blank=True)
    workflow_end = models.DateField(null=True, blank=True)
    responsible = models.CharField(max_length=160, blank=True, db_index=True)
    issue_status = models.CharField(max_length=180, blank=True, db_index=True)
    fabrication_ref = models.CharField(max_length=180, blank=True)

    class Meta:
        ordering = ["row_number"]
        indexes = [
            models.Index(fields=["import_batch", "discipline"]),
            models.Index(fields=["import_batch", "revision_family"]),
            models.Index(fields=["import_batch", "doc_status_group"]),
            models.Index(fields=["import_batch", "document_status"]),
        ]
        unique_together = ("import_batch", "row_number")
        verbose_name = "Documento DED engenharia"
        verbose_name_plural = "Documentos DED engenharia"

    def __str__(self) -> str:
        return self.document_number


class EngineeringMonitorImport(TimestampedModel):
    """Imported engineering monitor workbook normalized from the raw spreadsheet."""

    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    file_hash = models.CharField(max_length=64, db_index=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="engineering_monitor_imports",
    )
    detail_sheet = models.CharField(max_length=120, default="Sheet1")
    document_count = models.PositiveIntegerField(default=0)
    monitored_document_count = models.PositiveIntegerField(default=0)
    discipline_count = models.PositiveIntegerField(default=0)
    excluded_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["file_hash"]),
        ]
        verbose_name = "Importacao monitor engenharia"
        verbose_name_plural = "Importacoes monitor engenharia"

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.created_at:%d/%m/%Y %H:%M})"


class DatafySupplySnapshot(TimestampedModel):
    """Snapshot da area S02/Suprimentos consumido do PostgreSQL do DATAFY."""

    source_database = models.CharField(max_length=120, default="DATAFY")
    source_host = models.CharField(max_length=120, blank=True)
    filters_hash = models.CharField(max_length=64, db_index=True)
    filters = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    total_materials = models.PositiveIntegerField(default=0)
    total_drawings = models.PositiveIntegerField(default=0)
    material_rows = models.PositiveIntegerField(default=0)
    refreshed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datafy_supply_snapshots",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "filters_hash", "-created_at"]),
            models.Index(fields=["filters_hash", "-created_at"]),
        ]
        verbose_name = "Snapshot de suprimentos DATAFY"
        verbose_name_plural = "Snapshots de suprimentos DATAFY"

    def __str__(self) -> str:
        return f"{self.source_database} suprimentos ({self.created_at:%d/%m/%Y %H:%M})"

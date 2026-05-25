from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Client
from apps.core.models import TimestampedModel
from apps.datafy.models import Project
from apps.taskfy.models import Task


class Schedule(TimestampedModel):
    """Cronograma macro (vinculado ao Taskfy/Projeto)."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="schedules")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="schedules")
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = _("Cronograma")
        verbose_name_plural = _("Cronogramas")

    def __str__(self) -> str:
        return self.name


class ScheduleEvent(TimestampedModel):
    """Evento/marco de um cronograma (calendario)."""

    class Type(models.TextChoices):
        MILESTONE = "milestone", "Marco"
        MEETING = "meeting", "Reuniao"
        DELIVERY = "delivery", "Entrega"
        INSPECTION = "inspection", "Inspecao"
        TASK = "task", "Tarefa"
        OTHER = "other", "Outro"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planejado"
        IN_PROGRESS = "in_progress", "Em andamento"
        COMPLETED = "completed", "Concluido"
        DELAYED = "delayed", "Atrasado"
        CANCELLED = "cancelled", "Cancelado"

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="events")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="schedule_events")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=Type.choices, default=Type.MILESTONE)
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.PLANNED, db_index=True)
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="schedule_events")
    location = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=7, default="#0d6efd")

    class Meta:
        ordering = ["start_at"]
        verbose_name = _("Evento de cronograma")
        verbose_name_plural = _("Eventos de cronograma")
        indexes = [models.Index(fields=["start_at", "end_at"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.start_at:%d/%m %H:%M})"

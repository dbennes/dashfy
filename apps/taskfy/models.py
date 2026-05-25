from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Client
from apps.core.models import TimestampedModel
from apps.datafy.models import Project


class Board(TimestampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="taskfy_boards")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("Board")
        verbose_name_plural = _("Boards")

    def __str__(self) -> str:
        return self.name


class Task(TimestampedModel):
    class Status(models.TextChoices):
        BACKLOG = "backlog", "Backlog"
        TODO = "todo", "A fazer"
        DOING = "doing", "Em andamento"
        REVIEW = "review", "Revisao"
        DONE = "done", "Concluido"
        CANCELLED = "cancelled", "Cancelado"

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Critica"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="tasks")
    board = models.ForeignKey(Board, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="tasks")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="tasks")
    code = models.CharField(max_length=40, db_index=True)
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.TODO, db_index=True)
    priority = models.CharField(max_length=20, choices=Priority.choices,
                                default=Priority.MEDIUM, db_index=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="assigned_tasks")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="reported_tasks")
    due_date = models.DateField(null=True, blank=True, db_index=True)
    estimated_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    actual_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0, help_text="0 a 100")
    tags = models.CharField(max_length=255, blank=True, help_text="Tags separadas por virgula")

    class Meta:
        unique_together = ("client", "code")
        ordering = ["-due_date", "-id"]
        verbose_name = _("Tarefa")
        verbose_name_plural = _("Tarefas")
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.title}"

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone
        if not self.due_date or self.status in {self.Status.DONE, self.Status.CANCELLED}:
            return False
        return self.due_date < timezone.localdate()


class TaskComment(TimestampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                               null=True, related_name="task_comments")
    body = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.author} on {self.task}"

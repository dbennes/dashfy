from django.conf import settings
from django.db import models


class SavedView(models.Model):
    """View salva pelo usuario: nome + caminho + querystring."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="saved_views")
    name = models.CharField(max_length=120)
    module = models.CharField(max_length=40, help_text="datafy, taskfy, schedule, eclic")
    path = models.CharField(max_length=255)
    querystring = models.TextField()
    is_default = models.BooleanField(default=False)
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module", "name"]
        unique_together = ("user", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.module})"

    @property
    def full_url(self) -> str:
        if self.querystring:
            return f"{self.path}?{self.querystring}"
        return self.path

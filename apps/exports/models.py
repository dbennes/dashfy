from django.conf import settings
from django.db import models


class ExportLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    filename = models.CharField(max_length=200)
    file_format = models.CharField(max_length=10)
    module = models.CharField(max_length=40, blank=True)
    rows = models.IntegerField(default=0)
    query_params = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.file_format}) - {self.user}"

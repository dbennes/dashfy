import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_engineeringmonitorimport"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RosScheduleImport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revision", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("base_revision", models.CharField(max_length=64, unique=True)),
                ("original_filename", models.CharField(max_length=255)),
                ("file_size", models.PositiveIntegerField(default=0)),
                ("file_hash", models.CharField(max_length=64)),
                ("snapshot_date", models.DateField()),
                ("payload", models.JSONField(default=dict)),
                ("metadata", models.JSONField(default=dict)),
                ("imported_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ros_schedule_imports", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-pk"],
                "verbose_name": "ROS schedule import",
                "verbose_name_plural": "ROS schedule imports",
            },
        ),
    ]

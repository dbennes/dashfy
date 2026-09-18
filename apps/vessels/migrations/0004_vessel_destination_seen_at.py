from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vessels", "0003_vessel_voyage_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="vessel",
            name="destination_seen_at",
            field=models.DateTimeField(blank=True, null=True, editable=False,
                                       help_text="Observation time of the latest accepted destination declaration."),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vessels", "0002_vessel_last_provider_vesselposition_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="vessel",
            name="voyage_state",
            field=models.JSONField(blank=True, default=dict, editable=False,
                                   help_text="Observed port arrivals and departures from newer positions."),
        ),
    ]

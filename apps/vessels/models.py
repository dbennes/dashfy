from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


mmsi_validator = RegexValidator(r"^[0-9]{9}$", "MMSI must contain exactly nine digits.")
imo_validator = RegexValidator(r"^[0-9]{7}$", "IMO must contain exactly seven digits.")


class Vessel(models.Model):
    """The authenticated cockpit fleet; AIS never creates registrations itself."""

    mmsi = models.CharField(max_length=9, unique=True, validators=[mmsi_validator])
    name = models.CharField(max_length=120, blank=True)
    imo = models.CharField(max_length=7, blank=True, validators=[imo_validator])
    vessel_type = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    destination = models.CharField(max_length=120, blank=True)
    destination_seen_at = models.DateTimeField(null=True, blank=True, editable=False,
                                               help_text="Observation time of the latest accepted destination declaration.")
    eta = models.JSONField(default=dict, blank=True, help_text="Declared AIS month/day/hour/minute; no year is inferred.")
    draught = models.FloatField(null=True, blank=True)
    last_latitude = models.FloatField(null=True, blank=True)
    last_longitude = models.FloatField(null=True, blank=True)
    last_sog = models.FloatField(null=True, blank=True)
    last_cog = models.FloatField(null=True, blank=True)
    last_heading = models.FloatField(null=True, blank=True)
    last_navigational_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    last_static_seen = models.DateTimeField(null=True, blank=True)
    last_provider = models.CharField(max_length=32, blank=True, help_text="Channel that delivered the current position; the observation itself is always AIS.")
    voyage_state = models.JSONField(default=dict, blank=True, editable=False,
                                   help_text="Observed port arrivals and departures from newer positions.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "mmsi"]
        constraints = [
            models.CheckConstraint(check=models.Q(mmsi__regex=r"^[0-9]{9}$"), name="vessel_mmsi_nine_digits"),
            models.CheckConstraint(check=models.Q(last_latitude__isnull=True) | models.Q(last_latitude__range=(-90, 90)), name="vessel_latitude_range"),
            models.CheckConstraint(check=models.Q(last_longitude__isnull=True) | models.Q(last_longitude__range=(-180, 180)), name="vessel_longitude_range"),
        ]

    def __str__(self):
        return f"{self.name or 'Unnamed vessel'} ({self.mmsi})"

    def clean(self):
        super().clean()
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values_list("mmsi", flat=True).first()
            if original is not None and original != self.mmsi:
                raise ValidationError({"mmsi": "MMSI cannot be changed. Deactivate this vessel and register the new MMSI."})


class VesselPosition(models.Model):
    """Retained AIS observations. Stop tracking never deletes this history."""

    vessel = models.ForeignKey(Vessel, related_name="positions", on_delete=models.PROTECT)
    latitude = models.FloatField(validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.FloatField(validators=[MinValueValidator(-180), MaxValueValidator(180)])
    sog = models.FloatField(null=True, blank=True)
    cog = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    navigational_status = models.PositiveSmallIntegerField(null=True, blank=True)
    timestamp = models.DateTimeField()
    source = models.CharField(max_length=8, default="AIS", editable=False)
    provider = models.CharField(max_length=32, default="aisstream", db_index=True, editable=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp", "id"]
        indexes = [models.Index(fields=["vessel", "timestamp"], name="vessel_position_time_idx")]
        constraints = [
            models.UniqueConstraint(fields=["vessel", "timestamp"], name="vessel_position_unique_time"),
            models.CheckConstraint(check=models.Q(source="AIS"), name="vessel_position_ais_only"),
            models.CheckConstraint(check=models.Q(latitude__range=(-90, 90)), name="vessel_position_lat_range"),
            models.CheckConstraint(check=models.Q(longitude__range=(-180, 180)), name="vessel_position_lon_range"),
        ]

    def __str__(self):
        return f"{self.vessel_id}: {self.timestamp.isoformat()}"


class AISListenerState(models.Model):
    class Status(models.TextChoices):
        STOPPED = "stopped", "Stopped"
        IDLE = "idle", "Waiting for active vessels"
        CONNECTING = "connecting", "Connecting"
        CONNECTED = "connected", "Connected"
        RECONNECTING = "reconnecting", "Reconnecting"
        CONFIGURATION_ERROR = "configuration_error", "Configuration required"

    provider = models.CharField(max_length=32, primary_key=True, default="aisstream")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.STOPPED)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    active_vessel_count = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f"{self.provider}: {self.get_status_display()}"

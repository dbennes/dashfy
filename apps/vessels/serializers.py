"""Public AIS data and administrator-controlled fleet registration."""
from __future__ import annotations

import re

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Vessel
from .voyages import voyage_payload


def vessel_data(vessel: Vessel, *, now=None) -> dict:
    now = now or timezone.now()
    position = None
    age = None
    freshness = "NO_RECENT_AIS"
    if vessel.last_seen is not None and vessel.last_latitude is not None and vessel.last_longitude is not None:
        age = max(0, int((now - vessel.last_seen).total_seconds()))
        recent = max(0, int(getattr(settings, "AIS_RECENT_SECONDS", 600)))
        stale = max(recent, int(getattr(settings, "AIS_STALE_SECONDS", 3600)))
        freshness = "RECENT" if age <= recent else "STALE" if age <= stale else "NO_RECENT_AIS"
        position = {
            "latitude": vessel.last_latitude, "longitude": vessel.last_longitude,
            "timestamp": vessel.last_seen, "sog": vessel.last_sog, "cog": vessel.last_cog,
            "heading": vessel.last_heading, "navigational_status": vessel.last_navigational_status,
            "source": "AIS",
        }
    return {
        "id": vessel.pk, "name": vessel.name, "mmsi": vessel.mmsi, "imo": vessel.imo,
        "vessel_type": vessel.vessel_type, "is_active": vessel.is_active,
        "destination": vessel.destination, "eta": vessel.eta, "draught": vessel.draught,
        "last_position": position, "status": freshness, "age_seconds": age,
        "voyage": voyage_payload(vessel),
    }


class VesselRegistrationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, allow_blank=False, trim_whitespace=True)
    mmsi = serializers.CharField(
        min_length=9, max_length=9, trim_whitespace=True,
        validators=[UniqueValidator(queryset=Vessel.objects.all(), message="This MMSI is already registered.")],
    )
    imo = serializers.CharField(max_length=7, allow_blank=True, required=False, trim_whitespace=True)

    class Meta:
        model = Vessel
        fields = ("name", "mmsi", "imo", "vessel_type", "is_active")

    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: ["This field cannot be edited."] for key in sorted(unknown)})
        return super().to_internal_value(data)

    def validate_mmsi(self, value):
        if not re.fullmatch(r"[0-9]{9}", value):
            raise serializers.ValidationError("MMSI must contain exactly nine ASCII digits.")
        if self.instance is not None and value != self.instance.mmsi:
            raise serializers.ValidationError("MMSI cannot be changed after registration. Register a separate vessel instead.")
        return value

    def validate_imo(self, value):
        if not value:
            return ""
        if not re.fullmatch(r"[0-9]{7}", value):
            raise serializers.ValidationError("IMO must contain seven ASCII digits.")
        check = sum(int(digit) * weight for digit, weight in zip(value[:6], range(7, 1, -1))) % 10
        if check != int(value[-1]):
            raise serializers.ValidationError("IMO checksum is invalid.")
        return value

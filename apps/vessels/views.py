"""Authenticated fleet API. Historical tracks contain received AIS positions only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import logging

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from . import csvio
from .imports import ReportError, import_report
from .models import AISListenerState, Vessel, VesselPosition
from .serializers import VesselRegistrationSerializer, vessel_data


logger = logging.getLogger(__name__)
_POSITION_FIELDS = ("id", "latitude", "longitude", "timestamp", "sog", "cog", "heading", "navigational_status", "source")
_COLLECTOR_STATUSES = {"stopped", "idle", "connecting", "connected", "reconnecting", "configuration_error"}
_ERROR_CODES = {
    "missing_api_key", "no_active_vessels", "too_many_vessels", "invalid_mmsi",
    "provider_rejected", "compression_required", "connection_error", "database_error",
    "lock_lost", "heartbeat_expired", "invalid_bounding_boxes",
}
_IMPORT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_IMPORT_MAX_BYTES = 32 * 1024 * 1024
_IMPORT_PREVIEW = 50


def collection_status(*, now=None) -> dict:
    now = now or timezone.now()
    configured = bool(str(getattr(settings, "AISSTREAM_API_KEY", "") or "").strip())
    state = AISListenerState.objects.filter(provider="aisstream").first()
    status = state.status if state and state.status in _COLLECTOR_STATUSES else "stopped"
    heartbeat = state.heartbeat_at if state else None
    error_code = state.last_error_code if state and state.last_error_code in _ERROR_CODES else ""
    if not configured:
        status = "not_configured"
        error_code = "missing_api_key"
    elif status not in {"stopped", "configuration_error"} and (
        heartbeat is None or (now - heartbeat).total_seconds() > max(1, int(getattr(settings, "AIS_HEARTBEAT_TIMEOUT_SECONDS", 120)))
    ):
        status = "unavailable"
        error_code = "heartbeat_expired"
    return {
        "configured": configured, "status": status, "last_heartbeat": heartbeat,
        "connected_at": state.connected_at if state else None,
        "last_message_at": state.last_message_at if state else None,
        "active_vessel_count": Vessel.objects.filter(is_active=True).count(),
        "last_error_code": error_code,
    }


def _freshness(age_seconds: int) -> str:
    """The serializer's thresholds, so an imported fix never reads fresher than the map shows it."""
    recent = max(0, int(getattr(settings, "AIS_RECENT_SECONDS", 600)))
    stale = max(recent, int(getattr(settings, "AIS_STALE_SECONDS", 3600)))
    return "RECENT" if age_seconds <= recent else "STALE" if age_seconds <= stale else "NO_RECENT_AIS"



class VesselAPIView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["Pragma"] = "no-cache"
        return response

    def handle_exception(self, exc):
        if isinstance(exc, DatabaseError):
            # Never serialize driver/provider exceptions or connection secrets.
            logger.error("Vessel API database request failed", extra={"endpoint": type(self).__name__})
            return Response({"detail": "Vessel data is temporarily unavailable. Please try again."}, status=503)
        return super().handle_exception(exc)

    def require_manager(self, request):
        if not request.user.is_admin:
            raise PermissionDenied("Only administrators can manage vessel tracking.")

    def detail(self, vessel):
        now = timezone.now()
        return Response({
            "vessel": vessel_data(vessel, now=now),
            "can_manage": bool(self.request.user.is_admin),
            "collection": collection_status(now=now),
        })

    def save_registration(self, request, *, pk=None):
        self.require_manager(request)
        try:
            with transaction.atomic():
                # Serialize registrations/reactivations across API workers,
                # including the initially empty fleet, for the provider cap.
                AISListenerState.objects.get_or_create(provider="aisstream")
                AISListenerState.objects.select_for_update().get(provider="aisstream")
                vessel = get_object_or_404(Vessel.objects.select_for_update(), pk=pk) if pk is not None else None
                serializer = VesselRegistrationSerializer(vessel, data=request.data, partial=vessel is not None)
                serializer.is_valid(raise_exception=True)
                becoming_active = serializer.validated_data.get("is_active", vessel.is_active if vessel else True)
                if becoming_active and (vessel is None or not vessel.is_active):
                    maximum = min(200, max(1, int(getattr(settings, "AIS_MAX_ACTIVE_VESSELS", 200))))
                    if Vessel.objects.filter(is_active=True).count() >= maximum:
                        raise ValidationError({"is_active": [f"Tracking is limited to {maximum} active vessels. Stop tracking another vessel first."]})
                vessel = serializer.save()
        except IntegrityError:
            # A concurrent registration may have claimed the same MMSI.
            return Response({"detail": "Vessel registration conflicts with an existing record."}, status=409)
        return Response({"vessel": vessel_data(vessel)}, status=200 if pk is not None else 201)


class VesselListView(VesselAPIView):
    def get(self, request):
        now = timezone.now()
        return Response({
            "vessels": [vessel_data(vessel, now=now) for vessel in Vessel.objects.order_by("name", "mmsi")],
            "can_manage": bool(request.user.is_admin), "collection": collection_status(now=now),
        })

    def post(self, request):
        return self.save_registration(request)


class VesselDetailView(VesselAPIView):
    def get(self, request, pk):
        return self.detail(get_object_or_404(Vessel, pk=pk))

    def patch(self, request, pk):
        return self.save_registration(request, pk=pk)


class VesselLatestView(VesselAPIView):
    def get(self, request, pk):
        return self.detail(get_object_or_404(Vessel, pk=pk))


def _history_parameters(query, *, now):
    period = query.get("range", "24h")
    ranges = {"24h": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}
    if period == "custom":
        values = {}
        for field in ("start", "end"):
            try:
                value = parse_datetime(query.get(field, ""))
            except (ValueError, TypeError):
                value = None
            if value is None or timezone.is_naive(value):
                raise ValidationError({field: ["Use an ISO 8601 date and time with a timezone (Z or +hh:mm)."]})
            values[field] = value
        start, end = values["start"], values["end"]
        if start >= end:
            raise ValidationError({"end": ["End must be after start."]})
    elif period == "all":
        if "start" in query or "end" in query:
            raise ValidationError({"range": ["Use range=custom when specifying start or end."]})
        start, end = datetime(1970, 1, 1, tzinfo=dt_timezone.utc), now
    elif period in ranges:
        if "start" in query or "end" in query:
            raise ValidationError({"range": ["Use range=custom when specifying start or end."]})
        start, end = now - ranges[period], now
    else:
        raise ValidationError({"range": ["Choose all, 24h, 7d, 30d or custom."]})
    maximum = min(5000, max(2, int(getattr(settings, "AIS_MAX_TRACK_POINTS", 5000))))
    try:
        limit = int(query.get("limit", min(2000, maximum)))
    except (ValueError, TypeError):
        limit = 0
    if not 2 <= limit <= maximum:
        raise ValidationError({"limit": [f"Limit must be between 2 and {maximum} points."]})
    return period, start, end, limit


def _track(vessel, *, start, end, limit):
    """Stored AIS rows for the window, chronological; the caller slices to `limit`."""
    query = VesselPosition.objects.filter(
        vessel=vessel, source="AIS", timestamp__gte=start, timestamp__lte=end,
    ).order_by("timestamp", "pk")
    total = query.count()
    if total > limit:
        # The database ranks the interval; Python receives at most `limit`
        # real rows. Even spacing preserves the first and last AIS points.
        ranks = [1 + index * (total - 1) // (limit - 1) for index in range(limit)]
        query = query.annotate(_sample_row=Window(
            expression=RowNumber(), order_by=(F("timestamp").asc(), F("pk").asc()),
        )).filter(_sample_row__in=ranks)
    return query, total


class VesselPositionsView(VesselAPIView):
    def get(self, request, pk):
        vessel = get_object_or_404(Vessel, pk=pk)
        now = timezone.now()
        period, start, end, limit = _history_parameters(request.query_params, now=now)
        query, total = _track(vessel, start=start, end=end, limit=limit)
        positions = list(query.values(*_POSITION_FIELDS)[:limit])
        return Response({
            "vessel_id": vessel.pk, "positions": positions, "total_count": total,
            "returned_count": len(positions), "simplified": total > len(positions),
            "range": period, "start": start, "end": end, "collection": collection_status(now=now),
        })


class VesselStatusView(VesselAPIView):
    def get(self, request):
        return Response({"collection": collection_status(), "can_manage": bool(request.user.is_admin)})


def _csv_response(rows, *, filename: str) -> HttpResponse:
    """A plain HttpResponse: a CSV body must reach the browser unrendered."""
    response = HttpResponse(csvio.render(rows), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="' + filename + '"'
    return response


class VesselExportView(VesselAPIView):
    """Every registered vessel, positioned or not, so the file also serves as an import template."""

    def get(self, request):
        now = timezone.now()
        rows = [csvio.vessel_row(vessel) for vessel in Vessel.objects.order_by("name", "mmsi")]
        return _csv_response(rows, filename=csvio.filename("fleet-positions", now=now))


class VesselTrackExportView(VesselAPIView):
    """The same window, sampling and stored rows the drawn track uses; no point is invented."""

    def get(self, request, pk):
        vessel = get_object_or_404(Vessel, pk=pk)
        now = timezone.now()
        _period, start, end, limit = _history_parameters(request.query_params, now=now)
        query, _total = _track(vessel, start=start, end=end, limit=limit)
        rows = [csvio.position_row(vessel, position) for position in query[:limit]]
        return _csv_response(rows, filename=csvio.filename(vessel.mmsi + "-track", now=now))


class VesselImportView(VesselAPIView):
    """Administrator upload of a provider report; storage decisions stay in imports.py."""

    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        self.require_manager(request)
        upload = request.data.get("file")
        if not hasattr(upload, "read"):
            return Response({"detail": "Attach the provider report as the file field."}, status=400)
        if upload.size > _IMPORT_MAX_BYTES:
            return Response({"detail": "The report is larger than 32 MB. Export a narrower date range."}, status=400)
        raw, text = upload.read(), None
        for encoding in _IMPORT_ENCODINGS:
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            return Response({"detail": "Could not decode the report. Save it as UTF-8 CSV and retry."}, status=400)
        dry_run = str(request.data.get("dry_run", "")).strip().lower() in {"true", "1"}
        now = timezone.now()
        try:
            result = import_report(text, now=now, dry_run=dry_run)
        except ReportError as exc:
            return Response({"detail": str(exc)}, status=400)
        observations = sorted(result.observations, key=lambda item: item["timestamp"])
        return Response({
            "dry_run": dry_run, "parsed": result.parsed, "created": result.created,
            "duplicates": result.duplicates, "skipped": result.skipped,
            "vessels_advanced": result.vessels_advanced,
            # A report is as fresh as its most recent fix, not its oldest.
            "freshest_age_seconds": min((item["age_seconds"] for item in observations), default=None),
            "observations": [{
                "mmsi": item["mmsi"], "name": item["name"], "timestamp": item["timestamp"],
                "latitude": item["latitude"], "longitude": item["longitude"], "sog": item["sog"],
                "cog": item["cog"], "heading": item["heading"], "age_seconds": item["age_seconds"],
                "status": _freshness(item["age_seconds"]),
            } for item in observations[:_IMPORT_PREVIEW]],
            "issues": [str(issue) for issue in result.issues[:_IMPORT_PREVIEW]],
            "collection": collection_status(now=now),
        })


class VesselContainersView(VesselAPIView):
    """Trackfy containers and their open shipments, for the map's container panel.

    Read-only: the Taskfy database is never written from here. A Trackfy outage
    degrades to an empty list with a reason, so the map keeps working.
    """

    def get(self, request):
        from apps.core.tracking_source import map_containers_safe

        payload = map_containers_safe()
        if not payload.get("available"):
            # The upstream error can name hosts and credentials; keep it server-side.
            logger.warning("Trackfy container lookup failed for the vessel map")
            return Response({"available": False, "containers": [], "totals": payload.get("totals", {}),
                             "detail": "Trackfy is unavailable. Container data could not be loaded."})
        return Response(payload)


class VesselShipmentItemsView(VesselAPIView):
    """What is inside one Trackfy shipment, for the map's container panel."""

    def get(self, request, pk):
        from apps.core.tracking_source import shipment_items_safe

        payload = shipment_items_safe(pk)
        if not payload.get("available"):
            # The upstream error can name hosts and credentials; keep it server-side.
            logger.warning("Trackfy shipment item lookup failed for the vessel map")
            return Response({"available": False, "found": False, "items": [], "total_count": 0,
                             "detail": "Trackfy is unavailable. Shipment contents could not be loaded."})
        if not payload.get("found"):
            return Response({"detail": "This shipment no longer exists in Trackfy."}, status=404)
        return Response(payload)

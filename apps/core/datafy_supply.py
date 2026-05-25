from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.cache import cache
from django.db import transaction

from .models import DatafySupplySnapshot
from .real_sources import _construction_datafy, json_default


def _json_ready(value: Any) -> Any:
    return json.loads(json.dumps(value, default=json_default, ensure_ascii=False))


def supply_filters_hash(filters: dict[str, Any]) -> str:
    normalized = _json_ready(filters)
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def latest_supply_snapshot(filters: dict[str, Any]) -> DatafySupplySnapshot | None:
    filters_hash = supply_filters_hash(filters)
    return (
        DatafySupplySnapshot.objects
        .filter(is_active=True, filters_hash=filters_hash)
        .order_by("-created_at", "-id")
        .first()
    )


def refresh_supply_snapshot(filters: dict[str, Any], *, refreshed_by: Any = None) -> DatafySupplySnapshot:
    from django.conf import settings

    payload = _json_ready(_construction_datafy(filters))
    filters_hash = supply_filters_hash(filters)
    flow = payload.get("material_flow") or {}
    campaign_views = payload.get("supply_campaign_views") or []
    total_drawings = sum(
        int((view.get("totals") or {}).get("drawings") or 0)
        for view in campaign_views
    )
    user = getattr(refreshed_by, "_wrapped", refreshed_by)
    if not getattr(user, "is_authenticated", False):
        user = None

    with transaction.atomic():
        DatafySupplySnapshot.objects.filter(filters_hash=filters_hash, is_active=True).update(is_active=False)
        snapshot = DatafySupplySnapshot.objects.create(
            source_database=settings.DATAFY_DB_NAME,
            source_host=f"{settings.DATAFY_DB_HOST}:{settings.DATAFY_DB_PORT}",
            filters_hash=filters_hash,
            filters=_json_ready(filters),
            payload=payload,
            total_materials=int(flow.get("total") or 0),
            total_drawings=total_drawings,
            material_rows=len(payload.get("material_rows") or []),
            refreshed_by=user,
        )

    cache.clear()
    return snapshot

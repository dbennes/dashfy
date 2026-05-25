from __future__ import annotations

import hashlib
import json
from typing import Any


_TEXT_KEYS = (
    "supply_priority",
    "supply_drawing_q",
    "supply_revision",
    "supply_discipline",
    "supply_line",
    "supply_table",
    "supply_page",
    "supply_item",
    "supply_family",
    "supply_code_q",
    "supply_description_q",
    "campaign",
)
_NUMBER_KEYS = ("min_readiness", "supply_fab_min", "supply_erection_min")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_number(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed in {0, 25, 50, 80, 100} else 0


def normalized_supply_snapshot_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    raw = filters or {}
    normalized: dict[str, Any] = {}

    for key in _TEXT_KEYS:
        if key == "supply_discipline":
            normalized[key] = _clean_text(raw.get("supply_discipline") or raw.get("discipline"))
        elif key == "supply_revision":
            normalized[key] = _clean_text(raw.get(key)).upper()
        elif key == "campaign":
            normalized[key] = _clean_text(raw.get(key)).upper()
        else:
            normalized[key] = _clean_text(raw.get(key))

    for key in _NUMBER_KEYS:
        normalized[key] = _clean_number(raw.get(key))

    return normalized


def hash_supply_snapshot_filters(filters: dict[str, Any] | None) -> str:
    encoded = json.dumps(
        normalized_supply_snapshot_filters(filters),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

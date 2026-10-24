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
SUPPLY_RELEASE_SCOPE_VERSION = 1
_RELEASE_SCOPES = {"official", "preparing", "all"}


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
    # Pure normalization is also used to inspect persisted filters. Never
    # borrow the current request's scope for a snapshot without that metadata.
    scope = _clean_text(raw.get("release_scope")).lower()
    normalized: dict[str, Any] = {
        "release_scope": scope if scope in _RELEASE_SCOPES else "official",
        "release_scope_version": SUPPLY_RELEASE_SCOPE_VERSION,
    }

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


def scope_supply_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Bind a live read/write to the scope authorized for this request."""
    from .release_scope import current_release_scope

    return {
        **(filters or {}),
        "release_scope": current_release_scope(),
        "release_scope_version": SUPPLY_RELEASE_SCOPE_VERSION,
    }


def supply_snapshot_matches_scope(stored_filters: dict[str, Any] | None, scope: str | None = None) -> bool:
    """Legacy snapshots have unknown contents and cannot prove isolation."""
    if scope is None:
        from .release_scope import current_release_scope

        scope = current_release_scope()
    return bool(
        isinstance(stored_filters, dict)
        and scope in _RELEASE_SCOPES
        and stored_filters.get("release_scope") == scope
        and stored_filters.get("release_scope_version") == SUPPLY_RELEASE_SCOPE_VERSION
    )


def hash_supply_snapshot_filters(filters: dict[str, Any] | None) -> str:
    encoded = json.dumps(
        normalized_supply_snapshot_filters(filters),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

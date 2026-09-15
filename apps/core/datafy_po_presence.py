"""Match DATAFY Drawings' decision to expose persisted PO allocations.

Keep the guards aligned with ``catalog.drawings._coverage_for_item`` and
``catalog.units.to_canonical``. This projection reads metadata only: it does
not repair catalogue matches, change allocation quantities, or inspect stock.
"""

from __future__ import annotations

from decimal import Decimal
import re


# The six patterns and their precedence mirror catalog.stock's bar-length
# parser. The special structural recovery requires a unit_label, which the
# Drawings conversion path does not pass, so that recovery is not used here.
_LENGTH_RANGE = re.compile(
    r"\b(?:DRL|SRL|DOUBLE\s+RANDOM|SINGLE\s+RANDOM|RANDOM)?\s*"
    r"LENGTHS?\s*\(?\s*(\d+(?:[.,]\d+)?)\s*(?:TO|-)\s*"
    r"(\d+(?:[.,]\d+)?)\s*M(?:L|ETERS?|ETROS?)?\b", re.IGNORECASE,
)
_LENGTH_M = re.compile(
    r"[xX×]\s*(\d+(?:[.,]\d+)?)\s*(M(?:L|ETERS?|ETROS?)?)\b(?!M)", re.IGNORECASE,
)
_PIPE_LEADING_LENGTH = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(M(?:L|ETERS?|ETROS?)?)\s*"
    r"[xX×]\s*\d+(?:[.,]\d+)?\s*(?:\"|INCH(?:ES)?\b)", re.IGNORECASE,
)
_BARE_ML = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*ML\b", re.IGNORECASE)
_BARE_STRUCTURAL_MM = re.compile(
    r"[xX×]\s*(\d{4,5})(?!\d)(?!\s*(?:MM|M|ML|METERS?|METROS?)\b)", re.IGNORECASE,
)
_LENGTH_MM = re.compile(r"[xX×]\s*(\d{4,5})\s*MM\b", re.IGNORECASE)
_STRUCTURAL_FAMILIES = {
    "ANGLE", "C", "CHS", "FLAT_BAR", "HEA", "HEB", "HEM", "HP", "IPE",
    "IPN", "MC", "PFC", "RHS", "ROUND_BAR", "S", "SHS", "SMLS", "U_CHANNEL",
    "UB", "UC", "UPE", "UPN", "W",
}
# Only E/N from core.po_units' OCR fold can occur in LENGTH/LENGTHS.
_LENGTH_UNIT_FOLD = str.maketrans({
    "Ε": "E", "ε": "e", "Е": "E", "е": "e",
    "Ν": "N", "ν": "n", "Н": "N", "н": "n",
})


def _has_positive_bar_length(description: str, family_code: str) -> bool:
    """Preserve the source parser's first-match behavior, including zero."""
    text = str(description or "")
    family = str(family_code or "").upper()
    patterns = [_LENGTH_RANGE, _LENGTH_M]
    if family == "PIPE":
        patterns.append(_PIPE_LEADING_LENGTH)
    patterns.append(_BARE_ML)
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            # Unit scaling never changes positivity; no quantity conversion
            # is needed for the visibility decision.
            return Decimal(match.group(1).replace(",", ".")) > 0
    if family in _STRUCTURAL_FAMILIES:
        matches = list(_BARE_STRUCTURAL_MM.finditer(text))
        if matches:
            return Decimal(matches[-1].group(1)) > 0
    match = _LENGTH_MM.search(text)
    return bool(match and Decimal(match.group(1)) > 0)


def _conversion_blocks_po(unit: str, canonical_unit: str, description: str, family_code: str) -> bool:
    """Only LENGTH-to-m without a positive bar length fails conversion.

    Other units, including unknown units and ordinary counts, use DATAFY's
    existing conversion or its warned 1:1 fallback and do not hide a PO.
    """
    source_unit = str(unit or "").strip().translate(_LENGTH_UNIT_FOLD).lower().rstrip(". ")
    return (
        canonical_unit == "m"
        and source_unit in {"length", "lengths"}
        and not _has_positive_bar_length(description, family_code)
    )


def blocked_material_ids(conn) -> set[int]:
    """Return allocated item IDs whose Linked POs DATAFY would leave blank.

    Uses DASHFY's DATAFY connection adapter (dictionary rows). The latest
    CatalogMatch follows DATAFY's -created_at order, with ID as a deterministic
    tie-breaker. Actual field/allocation completion flags preserve existing
    allocation evidence, even when quantity or catalogue metadata is missing.
    No row is removed from scope, and this helper does not modify quantities.
    """
    cursor = conn.cursor()
    cursor.execute("""
        select mi.id as material_item_id, mi.quantity, mi.unit, mi.description,
               cm.id as catalog_match_id, ci.canonical_unit, mf.code as family_code
        from core_materialitem mi
        join core_extractedtable t on t.id = mi.table_id
        join core_document d on d.id = t.document_id
        left join catalog_catalogmatch cm on cm.id = (
            select latest.id from catalog_catalogmatch latest
            where latest.material_item_id = mi.id
            order by latest.created_at desc, latest.id desc
            limit 1
        )
        left join catalog_catalogitem ci on ci.id = cm.catalog_item_id
        left join catalog_materialfamily mf on mf.id = ci.family_id
        where exists (
            select 1 from catalog_allocation a where a.material_item_id = mi.id
        )
          and not coalesce(d.field_complete, false)
          and not coalesce(d.allocation_complete, false)
    """)
    blocked: set[int] = set()
    for raw in cursor.fetchall():
        row = dict(raw)
        if (
            row["catalog_match_id"] is None
            or row["quantity"] is None
            or Decimal(str(row["quantity"])) <= 0
            or _conversion_blocks_po(
                row["unit"], row["canonical_unit"], row["description"], row["family_code"],
            )
        ):
            blocked.add(int(row["material_item_id"]))
    return blocked

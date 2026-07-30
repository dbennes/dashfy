from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.real_sources import (
    _po_row_has_yard_actual,
    _supply_build_drawing_line_rows,
    _supply_campaign_views,
)


def _material(
    item_id: int,
    *,
    missing_qty: float = 0,
    yard_actual: bool = False,
    scope: str = "fabrication",
    document_id: int = 100,
) -> dict:
    return {
        "material_item_id": item_id,
        "document_id": document_id,
        "drawing_number": f"DWG-{document_id}",
        "original_filename": f"DWG-{document_id}.pdf",
        "revision": "A",
        "revision_detail": "-",
        "discipline": "PIPING",
        "line": f'4"-LINE-{document_id}',
        "campaign": "1st",
        "priority": 1,
        "scope": scope,
        "is_finalized": 0,
        "requested_qty": 1,
        "allocated_qty": 0 if missing_qty > 0 else 1,
        "missing_qty": missing_qty,
        "has_po": 0 if missing_qty > 0 else 1,
        "yard_actual": 1 if yard_actual else 0,
        "stock_free_na": 0,
        "stock_piece_count": 0,
        "stock_total_qty": 0,
        "stock_free_qty": 0,
        "family": "PIPE",
    }


def _drawing_row(rows: list[dict]) -> dict:
    grouped = _supply_build_drawing_line_rows(deepcopy(rows), limit=10_000)
    if len(grouped) != 1:
        raise AssertionError(f"Expected one grouped drawing, got {len(grouped)}")
    return grouped[0]


def _pending_row(view: dict, bucket: int) -> dict:
    return next(row for row in view["pending_rows"] if row["pending"] == bucket)


class SupplyPendingContractTests(SimpleTestCase):
    def test_at_yard_keeps_zero_datafy_pending_when_other_items_are_in_transit(self):
        rows = [
            _material(1, yard_actual=True),
            _material(2),
            _material(3),
        ]

        drawing = _drawing_row(rows)
        view = _supply_campaign_views(deepcopy(rows), [])[0]

        self.assertEqual(drawing["stage_total_items"], 3)
        self.assertEqual(drawing["stage_yard_items"], 1)
        self.assertEqual(drawing["drawing_pending"], 0)
        self.assertEqual(drawing["pending_bucket"], 0)
        self.assertEqual(_pending_row(view, 0)["at_yard"], 1)

    def test_at_yard_uses_datafy_pending_count_not_total_minus_yard(self):
        rows = [
            _material(1, yard_actual=True),
            _material(2),
            _material(3, missing_qty=1),
        ]

        drawing = _drawing_row(rows)
        view = _supply_campaign_views(deepcopy(rows), [])[0]

        self.assertEqual(drawing["stage_total_items"] - drawing["stage_yard_items"], 2)
        self.assertEqual(drawing["drawing_pending"], 1)
        self.assertEqual(drawing["pending_bucket"], 1)
        self.assertEqual(_pending_row(view, 1)["at_yard"], 1)
        self.assertEqual(_pending_row(view, 2)["at_yard"], 0)

    def test_pending_bucket_counts_rows_and_caps_at_eight(self):
        seven = [_material(index, missing_qty=7) for index in range(1, 8)]
        eight = [_material(index, missing_qty=1, document_id=200) for index in range(1, 9)]

        self.assertEqual(_drawing_row(seven)["pending_bucket"], 7)
        self.assertEqual(_drawing_row(eight)["pending_bucket"], 8)

    def test_drawing_without_yard_is_not_counted_in_at_yard_bucket(self):
        rows = [_material(1, missing_qty=1)]
        view = _supply_campaign_views(deepcopy(rows), [])[0]

        self.assertEqual(_pending_row(view, 1)["value"], 1)
        self.assertEqual(_pending_row(view, 1)["at_yard"], 0)

    def test_parallel_tracking_po_is_treated_as_available_at_yard(self):
        po_row = {"po_number": "PO-AVEON-PARALLEL-TRACKING"}
        material = _material(1)
        material.update({
            "yard_actual": 0,
            "po_numbers": "PO-AVEON-PARALLEL-TRACKING",
        })

        self.assertTrue(_po_row_has_yard_actual(po_row))
        drawing = _drawing_row([material])
        self.assertEqual(drawing["stage_yard_items"], 1)
        self.assertEqual(drawing["stage_no_yard_items"], 0)

    def test_compatible_parallel_stock_does_not_count_as_received(self):
        material = _material(1, missing_qty=1)
        material.update({
            "yard_actual": 0,
            "stock_po_numbers": "PO-AVEON-PARALLEL-TRACKING",
            "po_covering": (
                "No balance (AVE126POH00250, PO-AVEON-PARALLEL-TRACKING)"
            ),
        })

        drawing = _drawing_row([material])

        self.assertEqual(drawing["stage_yard_items"], 0)
        self.assertEqual(drawing["drawing_pending"], 1)

    def test_fabrication_assumed_is_grouped_with_fabrication(self):
        drawing = _drawing_row([
            _material(1, yard_actual=True, scope="fabrication_assumed"),
        ])

        self.assertEqual(drawing["scope"], "fabrication")

    def test_template_yard_branch_reads_drawing_pending(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "home.html"
        ).read_text(encoding="utf-8")
        block = source.split("function c3StagePendingBucket", 1)[1].split(
            "function c3PendingBucketFromCount", 1
        )[0]
        yard_branch = block.split("if (stage === 'yard')", 1)[1].split(
            "if (stage === 'no_yard')", 1
        )[0]

        self.assertIn("drawingPending", yard_branch)
        self.assertNotIn("c3ArrivalPendingItems", yard_branch)

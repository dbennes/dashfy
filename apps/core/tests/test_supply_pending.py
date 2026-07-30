from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.real_sources import (
    _po_row_has_yard_actual,
    _supply_build_drawing_line_rows,
    _supply_campaign_views,
    _supply_fully_at_yard_material_ids,
    _supply_item_has_yard_receipt,
    _supply_item_is_at_yard,
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
    def test_at_yard_places_partial_arrival_in_remaining_item_bucket(self):
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
        self.assertEqual(_pending_row(view, 0)["at_yard"], 0)
        self.assertEqual(_pending_row(view, 2)["at_yard"], 1)

    def test_at_yard_includes_partial_quantity_even_without_a_fully_received_item(self):
        material = _material(1)
        material["yard_allocated_qty"] = 0.25

        drawing = _drawing_row([material])
        view = _supply_campaign_views([deepcopy(material)], [])[0]

        self.assertFalse(_supply_item_is_at_yard(material))
        self.assertTrue(_supply_item_has_yard_receipt(material))
        self.assertEqual(drawing["stage_yard_items"], 0)
        self.assertEqual(drawing["stage_yard_received_items"], 1)
        self.assertEqual(_pending_row(view, 1)["at_yard"], 1)

    def test_at_yard_places_full_arrival_in_zero_pending_bucket(self):
        rows = [
            _material(1, yard_actual=True),
            _material(2, yard_actual=True),
            _material(3, yard_actual=True),
        ]

        drawing = _drawing_row(rows)
        view = _supply_campaign_views(deepcopy(rows), [])[0]

        self.assertEqual(drawing["stage_total_items"], 3)
        self.assertEqual(drawing["stage_yard_items"], 3)
        self.assertEqual(drawing["drawing_pending"], 0)
        self.assertEqual(drawing["pending_bucket"], 0)
        self.assertEqual(_pending_row(view, 0)["at_yard"], 1)

    def test_all_scope_is_default_and_counts_same_document_in_each_scope(self):
        rows = [
            _material(1, yard_actual=True, scope="fabrication", document_id=100),
            _material(2, yard_actual=True, scope="erection", document_id=100),
        ]

        views = _supply_campaign_views(deepcopy(rows), [])

        self.assertEqual([view["key"] for view in views], ["all", "fabrication", "erection"])
        self.assertEqual(views[0]["totals"]["drawings"], 2)
        self.assertEqual(views[1]["totals"]["drawings"], 1)
        self.assertEqual(views[2]["totals"]["drawings"], 1)
        self.assertEqual(_pending_row(views[0], 0)["at_yard"], 2)

    def test_at_yard_keeps_finalized_drawing_in_finalized_bucket(self):
        material = _material(1, yard_actual=True)
        material["is_finalized"] = 1

        drawing = _drawing_row([material])
        view = _supply_campaign_views([deepcopy(material)], [])[0]

        self.assertEqual(drawing["drawing_finalized"], 1)
        self.assertEqual(drawing["stage_yard_items"], 1)
        self.assertEqual(drawing["stage_yard_received_items"], 1)
        self.assertEqual(_pending_row(view, -1)["at_yard"], 1)

    def test_partial_yard_allocation_does_not_mark_material_fully_received(self):
        material = _material(1)
        material["requested_qty"] = 6
        po_rows = [
            {
                "allocation_id": 10,
                "material_item_id": 1,
                "qty_allocated": 2,
                "po_number": "PO-ARRIVED",
                "procurement_plan_stage": "Delivery At Yard",
                "procurement_plan_kind": "Actual",
                "procurement_plan_date": "2026-01-01",
            },
            {
                "allocation_id": 11,
                "material_item_id": 1,
                "qty_allocated": 4,
                "po_number": "PO-IN-TRANSIT",
                "procurement_plan_stage": "Delivery At Yard",
                "procurement_plan_kind": "Forecast",
                "procurement_plan_date": "2026-09-01",
            },
        ]

        self.assertNotIn(
            1,
            _supply_fully_at_yard_material_ids([material], po_rows),
        )

        po_rows[1]["procurement_plan_kind"] = "Actual"
        po_rows[1]["procurement_plan_date"] = "2026-07-01"
        self.assertIn(
            1,
            _supply_fully_at_yard_material_ids([material], po_rows),
        )

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

    def test_parallel_tracking_po_is_yard_fallback_when_explicit_state_is_missing(self):
        po_row = {"po_number": "PO-AVEON-PARALLEL-TRACKING"}
        material = _material(1)
        material.update({
            "po_numbers": "PO-AVEON-PARALLEL-TRACKING",
        })
        material.pop("yard_actual")

        self.assertTrue(_po_row_has_yard_actual(po_row))
        drawing = _drawing_row([material])
        self.assertEqual(drawing["stage_yard_items"], 1)
        self.assertEqual(drawing["stage_no_yard_items"], 0)

    def test_explicit_partial_parallel_tracking_state_is_not_overridden(self):
        material = _material(1)
        material.update({
            "yard_actual": 0,
            "po_numbers": "PO-AVEON-PARALLEL-TRACKING",
        })

        self.assertFalse(_supply_item_is_at_yard(material))
        drawing = _drawing_row([material])
        self.assertEqual(drawing["stage_yard_items"], 0)
        self.assertEqual(drawing["stage_no_yard_items"], 1)

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

    def test_template_yard_branch_reads_arrival_pending(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "home.html"
        ).read_text(encoding="utf-8")
        block = source.split("function c3StagePendingBucket", 1)[1].split(
            "function c3PendingBucketFromCount", 1
        )[0]
        yard_branch = block.split(
            "if (stage === 'yard' || stage === 'no_yard')", 1
        )[1].split("var keys", 1)[0]

        self.assertIn("c3ArrivalPendingItems", yard_branch)
        self.assertNotIn("drawingPending", yard_branch)

    def test_template_yard_filter_includes_partial_arrivals(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "home.html"
        ).read_text(encoding="utf-8")
        block = source.split("function c3DrawingStageMatches", 1)[1].split(
            "function c3StagePendingBucket", 1
        )[0]

        self.assertIn("return totalItems > 0 && yardReceivedItems > 0", block)
        self.assertIn("forecast.forecastReceived > 0", block)
        self.assertNotIn("yardItems >= totalItems", block)

    def test_forecast_yard_pending_does_not_treat_no_po_assumption_as_received(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "home.html"
        ).read_text(encoding="utf-8")
        block = source.split("function c3ArrivalPendingItems", 1)[1].split(
            "function c3DrawingPendingBucket", 1
        )[0]

        self.assertIn("forecast.total || 0", block)
        self.assertIn("forecast.forecastAvailable || 0", block)
        self.assertNotIn("forecast.noPoAssumption", block)

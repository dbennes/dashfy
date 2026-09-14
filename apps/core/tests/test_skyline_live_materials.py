from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import skyline_material_source as source


class SkylineLiveMaterialsTests(SimpleTestCase):
    day = date(2026, 9, 14)
    line = '4"-DN-473605'

    def document(self, pk=1, **changes):
        value = {"document_id": pk, "project_id": 1, "line": self.line + "-STD-H",
                 "status": "success", "has_materials": True,
                 "field_complete": False, "field_complete_at": None}
        value.update(changes)
        return value

    def item(self, pk=1, **changes):
        value = {"material_item_id": pk, "document_id": 1, "category": "BOLTS",
                 "family": "Stud Bolt", "requested_qty": 10, "allocated_qty": 10,
                 "scope": "erection", "yard_actual": 0, "yard_qty": 0, "has_po": 1}
        value.update(changes)
        return value

    def reading(self, pk=1, **changes):
        value = {"document_id": pk, "extractor_version": 2, "supports_found": 0,
                 "read_at": self.day}
        value.update(changes)
        return value

    def aggregate(self, items=(), *, documents=None, supports=(), readings=None, lines=None):
        return source.build_material_readiness(
            lines or [self.line], documents if documents is not None else [self.document()],
            list(items), list(supports), readings if readings is not None else [self.reading()],
            observed_on=self.day,
        )

    def test_live_line_identity_parses_size_service_and_complete_number(self):
        self.assertEqual(source.line_identity(' 1.1/2"-CM-423045 '), source.line_identity('1-1/2"-CM-423045-160S-J3'))
        self.assertEqual(source.line_identity(self.line + "-STD-H"), self.line)
        for other in ['2"-DN-473605', '4"-DC-473605', '4"-DN-4736050', '4"-DN-473606']:
            self.assertNotEqual(source.line_identity(other), self.line)

    def test_missing_line_does_not_inherit_neighbor_materials(self):
        data = self.aggregate([self.item(yard_actual=1)], lines=[self.line, self.line + "0"])
        self.assertEqual(data[self.line]["erection"]["status"], "ready")
        self.assertTrue(all(row["status"] == "unknown" for row in data[self.line + "0"].values()))

    def test_multiple_drawings_are_aggregated_before_green(self):
        data = self.aggregate(
            [self.item(yard_actual=1), self.item(2, document_id=2, category="GASKETS", family="Gasket")],
            documents=[self.document(), self.document(2)], readings=[self.reading(), self.reading(2)],
        )[self.line]
        self.assertEqual(data["erection"]["status"], "partial")
        self.assertEqual(data["erection"]["counts"]["total_items"], 2)

    def test_cross_project_identity_is_ambiguous(self):
        data = self.aggregate([self.item(yard_actual=1)], documents=[self.document(), self.document(2, project_id=2)])
        self.assertTrue(all(row["status"] == "unknown" for row in data[self.line].values()))

    def test_full_mto_absence_is_not_applicable(self):
        categories = self.aggregate()[self.line]
        self.assertTrue(all(row["status"] == "not_applicable" for row in categories.values()))

    def test_partial_extraction_cannot_prove_absence_or_complete_readiness(self):
        data = self.aggregate([self.item(yard_actual=1)], documents=[self.document(status="pending")])[self.line]
        self.assertEqual(data["erection"]["status"], "partial")
        self.assertEqual(data["valves"]["status"], "unknown")

    def test_known_unreceived_scope_is_pending_even_if_po_fully_covers_it(self):
        categories = self.aggregate([self.item()])[self.line]
        self.assertEqual(categories["erection"]["status"], "pending")
        self.assertEqual(categories["erection"]["counts"]["pending_items"], 1)

    def test_po_counts_include_unallocated_scope_without_conflating_po_and_receipt(self):
        result = self.aggregate([
            self.item(yard_actual=1),
            self.item(2, allocated_qty=3),
            self.item(3, allocated_qty=0, has_po=0, stock_po_numbers="CATALOG-PO-999"),
        ])[self.line]["erection"]
        counts = result["counts"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(counts["total_items"], 3)
        self.assertEqual(counts["items_with_po"], 2)
        self.assertEqual(counts["items_without_po"], 1)
        self.assertEqual(counts["fully_po_allocated_items"], 1)
        self.assertEqual(counts["partly_po_allocated_items"], 1)
        self.assertEqual(counts["ready_items"], 1)

    def test_po_quantity_counts_require_known_positive_request(self):
        result = self.aggregate([
            self.item(requested_qty="NaN"),
            self.item(2, requested_qty=0),
            self.item(3, allocated_qty=0),
        ])[self.line]["erection"]
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["counts"]["items_with_po"], 3)
        self.assertEqual(result["counts"]["fully_po_allocated_items"], 0)
        self.assertEqual(result["counts"]["partly_po_allocated_items"], 0)

    def test_no_required_items_has_zero_po_counts(self):
        for category in self.aggregate()[self.line].values():
            self.assertEqual(category["status"], "not_applicable")
            for key in ("items_with_po", "items_without_po", "fully_po_allocated_items", "partly_po_allocated_items"):
                self.assertEqual(category["counts"][key], 0)

    def test_partly_received_quantity_is_amber(self):
        data = self.aggregate([self.item(yard_qty=2)])[self.line]["erection"]
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["counts"]["ready_items"], 0)

    def test_demolition_and_pipe_support_u_bolts_do_not_pollute_erection(self):
        categories = self.aggregate([
            self.item(scope="other"),
            self.item(2, category="SUPPORTS", family="U-Bolt"),
        ])[self.line]
        self.assertEqual(categories["erection"]["status"], "not_applicable")
        self.assertEqual(categories["supports"]["status"], "pending")

    def test_invalid_quantities_never_create_green(self):
        for qty in [None, "NaN", "Infinity", -1, 0]:
            with self.subTest(qty=qty):
                data = self.aggregate([self.item(requested_qty=qty, yard_actual=1)])[self.line]["erection"]
                self.assertEqual(data["status"], "unknown")

    def test_support_occurrences_are_not_deduplicated_by_design_reference(self):
        occurrences = [
            {"id": 1, "document_id": 1, "support_reference": "PS-BN-SS-1"},
            {"id": 2, "document_id": 1, "support_reference": "PS-BN-SS-1"},
        ]
        result = self.aggregate(supports=occurrences)[self.line]["supports"]
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["counts"]["support_occurrences"], 2)

    def test_support_receipt_does_not_prove_unlinked_geometry_fabrication(self):
        result = self.aggregate(
            [self.item(category="SUPPORTS", yard_actual=1)],
            supports=[{"id": 1, "document_id": 1}],
        )[self.line]["supports"]
        self.assertEqual(result["status"], "partial")

    def test_legacy_support_reader_cannot_establish_no_support_scope(self):
        result = self.aggregate(readings=[self.reading(extractor_version=1)])[self.line]
        self.assertEqual(result["supports"]["status"], "unknown")
        self.assertEqual(result["erection"]["status"], "not_applicable")

    def test_reader_positive_scope_survives_missing_geometry_table_rows(self):
        result = self.aggregate(readings=[self.reading(supports_found=3)])[self.line]["supports"]
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["counts"]["support_occurrences"], 3)
        self.assertFalse(result["counts"]["support_scope_complete"])

    def test_field_completion_is_dated_physical_evidence_allocation_completion_is_not(self):
        items = [self.item(category="VALVES", family="Valve")]
        finished = self.aggregate(items, documents=[self.document(field_complete=True, field_complete_at=self.day)])[self.line]
        allocation_only = self.aggregate(items, documents=[self.document(allocation_complete=True)])[self.line]
        future = self.aggregate(items, documents=[self.document(field_complete=True, field_complete_at=date(2026, 9, 15))])[self.line]
        self.assertEqual(finished["valves"]["status"], "ready")
        self.assertEqual(allocation_only["valves"]["status"], "pending")
        self.assertEqual(future["valves"]["status"], "pending")

    def test_receipt_quantities_are_deduplicated_and_split_allocations_require_full_quantity(self):
        item = self.item()
        receipt = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 4,
                   "po_extra_fields": {"procurement_tracker": {"yard_actual": "2020-01-01"}}}
        source.enrich_material_receipts([item], [receipt, dict(receipt)])
        self.assertEqual(item["yard_qty"], 4)
        self.assertEqual(item["yard_actual"], 0)
        source.enrich_material_receipts([item], [receipt, dict(receipt, allocation_id=2, qty_allocated=6)])
        self.assertEqual(item["yard_actual"], 1)

    def test_synthetic_support_tracking_po_is_coverage_without_physical_receipt(self):
        item = self.item(category="SUPPORTS")
        placeholder = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                       "po_number": "PO-AVEON-PARALLEL-TRACKING", "product_code": "PIPE_SUPPORT_TRACKING"}
        before = deepcopy(placeholder)
        source.enrich_material_receipts([item], [placeholder])
        self.assertEqual(placeholder, before)
        self.assertEqual(item["has_po"], 1)
        self.assertEqual(item["yard_actual"], 0)
        self.assertEqual(item["yard_qty"], 0)
        actual = dict(placeholder, po_extra_fields={"procurement_tracker": {"yard_actual": "2020-01-01"}})
        source.enrich_material_receipts([item], [actual])
        self.assertEqual(item["yard_actual"], 1)

    def test_future_actual_yard_date_does_not_prove_receipt(self):
        item = self.item()
        receipt = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                   "po_extra_fields": {"procurement_tracker": {"yard_actual": (date.today() + timedelta(days=10)).isoformat()}}}
        source.enrich_material_receipts([item], [receipt])
        self.assertEqual(item["yard_actual"], 0)
        self.assertEqual(item["yard_qty"], 0)

    def test_genuine_parallel_supply_keeps_existing_datafy_yard_rule(self):
        item = self.item(category="VALVES")
        receipt = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                   "po_number": "PO-AVEON-PARALLEL-TRACKING", "product_code": "REAL-VALVE"}
        source.enrich_material_receipts([item], [receipt])
        self.assertEqual(item["yard_actual"], 1)

    def test_empty_exact_tracker_blocks_po_wide_actual_on_a_sibling_item(self):
        items = [self.item(), self.item(2)]
        parent = {"procurement_plan_stage": "Delivery at yard", "procurement_plan_kind": "Actual",
                  "procurement_plan_date": "2020-01-01", "qty_allocated": 10}
        allocations = [
            dict(parent, material_item_id=1, allocation_id=1,
                 po_extra_fields={"procurement_tracker": {"yard_actual": "2020-01-01"}}),
            dict(parent, material_item_id=2, allocation_id=2,
                 po_extra_fields={"procurement_tracker": {"yard_actual": ""}}),
        ]
        source.enrich_material_receipts(items, allocations)
        self.assertEqual([item["yard_actual"] for item in items], [1, 0])

    def test_raw_tracker_is_authoritative_and_untyped_parent_actual_is_not(self):
        for raw, expected in [
            ({"_procurement_tracker": True, "Delivery At Yard Actual": "2020-01-01"}, 1),
            ({"_procurement_tracker": True, "Delivery At Yard Actual": ""}, 0),
            ({}, 0),
        ]:
            item = self.item()
            allocation = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                          "raw_row": raw, "procurement_plan_stage": "Delivery at yard",
                          "procurement_plan_kind": "Actual", "procurement_plan_date": "2020-01-01"}
            source.enrich_material_receipts([item], [allocation])
            self.assertEqual(item["yard_actual"], expected)

    def test_daily_item_proof_requires_current_unique_po_and_line_identity(self):
        daily = {"source_type": "daily_procurement_plan", "mapping": "explicit_line",
                 "purchase_order_id": 8, "po_number_in_plan": "PO-123", "line_number": "10",
                 "stage": "Delivery at yard", "kind": "Actual", "date": "2020-01-01"}
        allocation = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                      "po_id": 8, "po_number": "PO-123", "po_item_id": 80, "po_line_number": "10.0"}
        po_identities = [{"po_id": 8, "po_number": "PO-123"}]
        item_identities = [{"po_id": 8, "po_item_id": 80, "line_number": "10"}]
        for change, expected in [({}, 1), ({"purchase_order_id": 9}, 0), ({"line_number": "11"}, 0),
                                 ({"ambiguous": True}, 0), ({"partial_actual": True}, 0),
                                 ({"po_number_in_plan": "PO-999"}, 0)]:
            item = self.item()
            row = dict(allocation, po_extra_fields={"daily_procurement_plan": dict(daily, **change)})
            source.enrich_material_receipts([item], [row], po_identities, item_identities)
            self.assertEqual(item["yard_actual"], expected, change)
        item = self.item()
        row = dict(allocation, po_extra_fields={"daily_procurement_plan": daily})
        source.enrich_material_receipts([item], [row], po_identities,
                                        item_identities + [{"po_id": 8, "po_item_id": 81, "line_number": "10"}])
        self.assertEqual(item["yard_actual"], 0)

    def test_parent_lots_require_every_unscoped_lot_arrived_and_unique_po(self):
        timeline = [{"stage": "Delivery at yard", "kind": "Actual", "date": "2020-01-01"}]
        parent = {"source_type": "daily_procurement_plan", "po_number_in_plan": "PO-123",
                  "source_rows": [{"timeline": timeline}, {"timeline": timeline}]}
        allocation = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                      "po_id": 8, "po_number": "PO-123", "procurement_plan_payload": {"daily_plan": parent}}
        identities = [{"po_id": 8, "po_number": "PO-123"}]
        item = self.item()
        source.enrich_material_receipts([item], [allocation], identities)
        self.assertEqual(item["yard_actual"], 1)
        for second_lot in [{"timeline": []}, {"timeline": timeline, "has_item_reference": True},
                           {"timeline": timeline, "tags": ["04-RV-466"]},
                           {"timeline": [dict(timeline[0], date="2999-01-01")] }]:
            altered = deepcopy(allocation)
            altered["procurement_plan_payload"]["daily_plan"]["source_rows"][1] = second_lot
            item = self.item()
            source.enrich_material_receipts([item], [altered], identities)
            self.assertEqual(item["yard_actual"], 0)
        item = self.item()
        source.enrich_material_receipts([item], [allocation], identities + [{"po_id": 9, "po_number": "PO123"}])
        self.assertEqual(item["yard_actual"], 0)

    def test_daily_tag_requires_current_unique_tag_identity(self):
        daily = {"source_type": "daily_procurement_plan", "mapping": "exact_unique_tag",
                 "purchase_order_id": 8, "po_number_in_plan": "PO-123", "matched_tags": ["04-RV-466"],
                 "stage": "Delivery at yard", "kind": "Actual", "date": "2020-01-01"}
        allocation = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                      "po_id": 8, "po_number": "PO-123", "po_item_id": 80,
                      "po_description": "Relief valve 04-RV-466",
                      "po_extra_fields": {"daily_procurement_plan": daily}}
        identities = [{"po_id": 8, "po_number": "PO-123"}]
        item_identities = [{"po_id": 8, "po_item_id": 80, "description": "Relief valve 04-RV-466"}]
        item = self.item()
        source.enrich_material_receipts([item], [allocation], identities, item_identities)
        self.assertEqual(item["yard_actual"], 1)
        source.enrich_material_receipts([item], [allocation], identities,
                                        item_identities + [{"po_id": 8, "po_item_id": 81, "description": "Valve 04-RV-466"}])
        self.assertEqual(item["yard_actual"], 0)
        source.enrich_material_receipts([item], [dict(allocation, po_description="Valve 04-RV-999")], identities, item_identities)
        self.assertEqual(item["yard_actual"], 0)

    def test_daily_consensus_must_still_match_valid_parent_current(self):
        current = {"stage": "Delivery at yard", "kind": "Actual", "date": "2020-01-01"}
        parent = {"source_type": "daily_procurement_plan", "po_number_in_plan": "PO-123",
                  "item_scope": "po_consensus", "current": current, "timeline": [current]}
        daily = dict(current, source_type="daily_procurement_plan", mapping="exact_po_consensus",
                     purchase_order_id=8, po_number_in_plan="PO-123")
        allocation = {"material_item_id": 1, "allocation_id": 1, "qty_allocated": 10,
                      "po_id": 8, "po_number": "PO-123", "po_item_id": 80,
                      "procurement_plan_payload": {"daily_plan": parent},
                      "po_extra_fields": {"daily_procurement_plan": daily}}
        identities = [{"po_id": 8, "po_number": "PO-123"}]
        item = self.item()
        source.enrich_material_receipts([item], [allocation], identities)
        self.assertEqual(item["yard_actual"], 1)
        stale = deepcopy(allocation)
        stale["procurement_plan_payload"]["daily_plan"]["current"] = dict(current, date="2020-02-01")
        source.enrich_material_receipts([item], [stale], identities)
        self.assertEqual(item["yard_actual"], 0)
        changed_parent = deepcopy(allocation)
        changed_parent["procurement_plan_payload"]["daily_plan"]["po_number_in_plan"] = "PO-999"
        source.enrich_material_receipts([item], [changed_parent], identities)
        self.assertEqual(item["yard_actual"], 0)

    def test_physical_valve_tag_overrides_generic_instrument_classification(self):
        categories = self.aggregate([
            self.item(category="INSTRUMENTS", family="Instrument", component_category="valve"),
        ])[self.line]
        self.assertEqual(categories["valves"]["status"], "pending")
        self.assertEqual(categories["valves"]["counts"]["total_items"], 1)
        demolition = self.aggregate([
            self.item(category="INSTRUMENTS", family="Instrument", component_category="valve", scope="other"),
        ])[self.line]
        self.assertEqual(demolition["valves"]["status"], "not_applicable")

    def test_data_source_failure_keeps_spool_screen_available_with_explanation(self):
        with patch.object(source, "skyline_material_readiness", side_effect=RuntimeError("offline")), patch.object(source.logger, "exception"):
            result = source.skyline_material_readiness_safe([self.line], as_of_date=self.day)
        self.assertEqual(result[self.line]["valves"]["status"], "unknown")
        self.assertIn("temporarily unavailable", result[self.line]["valves"]["note"])

"""Without PO follows blank Linked POs in the DATAFY Drawings export."""
from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import real_sources as source
from apps.core.tests.test_supply_pending import _material


class SupplyPoPresenceTests(SimpleTestCase):
    def rows(self):
        allocated = _material(1)
        no_po = _material(2, missing_qty=1)
        no_balance = dict(_material(3, missing_qty=1), stock_piece_count=2, stock_free_qty=0)
        free_stock = dict(_material(4, missing_qty=1), stock_piece_count=2, stock_free_qty=5)
        unmatched = dict(_material(5, missing_qty=1), stock_free_na=1)
        finalized = dict(_material(6, missing_qty=1), is_finalized=1)
        return [allocated, no_po, no_balance, free_stock, unmatched, finalized]

    def test_without_po_is_complement_of_allocated_items_and_includes_gap_reasons(self):
        for view in source._supply_campaign_views(self.rows(), [])[:2]:
            totals = view['totals']
            self.assertEqual((totals['total'], totals['po'], totals['no_po']), (5, 1, 4))
            self.assertEqual(totals['total'], totals['po'] + totals['no_po'])
            self.assertEqual(totals['no_balance'], 1)
            self.assertEqual(totals['not_allocated'], 1)
            self.assertEqual(totals['catalog_issue'], 1)
            self.assertEqual(totals['unallocated'], 4)
            for row in view['executive']['campaign_rows']:
                self.assertEqual(row['unallocated'], row['no_po'])
                self.assertEqual(row['risk_items'], row['no_po'] + row['no_yard'])

    def test_drawing_counts_and_without_po_filter_include_depleted_stock(self):
        drawing = source._supply_build_drawing_line_rows(self.rows())[0]
        self.assertEqual((drawing['active_items'], drawing['with_po'], drawing['without_po']), (5, 1, 4))
        self.assertEqual(drawing['no_balance'], 1)
        self.assertEqual(drawing['unallocated'], 4)
        self.assertEqual(drawing['stage_no_po_items'], 4)
        self.assertEqual(drawing['stage_no_po_pending'], 4)
        self.assertEqual(drawing['stage_no_balance_items'], 1)

    def test_partial_quantity_with_linked_po_is_not_without_po(self):
        item = dict(_material(1, missing_qty=7), requested_qty=10, allocated_qty=3, has_po=1)
        totals = source._supply_campaign_views([item], [])[0]['totals']
        self.assertEqual((totals['total'], totals['po'], totals['no_po']), (1, 1, 0))

    def test_unresolved_identity_does_not_gain_po_from_raw_allocation(self):
        item = dict(_material(1), allocated_qty=1, has_po=0, stock_free_na=1)
        self.assertEqual(source._supply_po_gap_status(item), 'catalog_issue')
        totals = source._supply_campaign_views([item], [])[0]['totals']
        self.assertEqual((totals['po'], totals['no_po'], totals['catalog_issue']), (0, 1, 1))

    def test_linked_po_at_zero_allocated_quantity_matches_export_presence(self):
        item = dict(_material(1, missing_qty=1), allocated_qty=0, has_po=1)
        totals = source._supply_campaign_views([item], [{'material_item_id': 1, 'po_number': 'PO-1', 'qty_allocated': 0}])[0]['totals']
        self.assertEqual((totals['po'], totals['no_po']), (1, 0))

    @patch.object(source, '_supply_datafy_stock_lookup', return_value={})
    def test_older_snapshot_is_recomputed_using_inclusive_without_po_rule(self, _lookup):
        payload = {'material_rows': deepcopy(self.rows()), 'material_scope_items': self.rows(),
                   'supply_campaign_views': [{'key': 'all', 'totals': {'total': 5, 'po': 1, 'no_po': 3, 'no_balance': 1}}]}
        source._supply_normalize_operational_payload(payload)
        self.assertEqual(payload['supply_campaign_views'][0]['totals']['no_po'], 4)
        self.assertEqual(payload['drawing_line_rows'][0]['without_po'], 4)

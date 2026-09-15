from __future__ import annotations

import sqlite3
from unittest import TestCase

from apps.core.datafy_po_presence import _conversion_blocks_po, blocked_material_ids


class DatafyPoPresenceTests(TestCase):
    """Run the real projection query on an isolated source schema."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            create table core_document (id integer primary key, field_complete boolean, allocation_complete boolean);
            create table core_extractedtable (id integer primary key, document_id integer);
            create table core_materialitem (id integer primary key, table_id integer, quantity numeric, unit text, description text);
            create table catalog_materialfamily (id integer primary key, code text);
            create table catalog_catalogitem (id integer primary key, family_id integer, canonical_unit text);
            create table catalog_catalogmatch (id integer primary key, material_item_id integer, catalog_item_id integer, created_at text);
            create table catalog_allocation (id integer primary key, material_item_id integer, qty_allocated numeric);
            insert into catalog_materialfamily values (1, 'PIPE');
            insert into catalog_catalogitem values (1, 1, 'm');
            insert into catalog_catalogitem values (2, 1, 'un');
        """)

    def item(self, pk, *, match=True, quantity=1, unit="un", description="PIPE",
             field_complete=False, allocation_complete=False, allocation=True, allocated=1):
        self.conn.execute("insert into core_document values (?, ?, ?)", (pk, field_complete, allocation_complete))
        self.conn.execute("insert into core_extractedtable values (?, ?)", (pk, pk))
        self.conn.execute("insert into core_materialitem values (?, ?, ?, ?, ?)", (pk, pk, quantity, unit, description))
        if match:
            self.conn.execute("insert into catalog_catalogmatch values (?, ?, 1, '2026-09-01')", (pk, pk))
        if allocation:
            self.conn.execute("insert into catalog_allocation values (?, ?, ?)", (pk, pk, allocated))

    def test_unmatched_allocated_item_is_blocked_without_changing_source(self):
        self.item(1, match=False)
        self.item(2, match=False, allocation=False)
        self.item(3)
        before = list(self.conn.iterdump())
        self.conn.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in {
            sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
        } else sqlite3.SQLITE_OK)
        self.assertEqual(blocked_material_ids(self.conn), {1})
        self.conn.set_authorizer(None)
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_quantity_guard_does_not_treat_zero_allocation_as_missing_match(self):
        for pk, quantity in ((1, None), (2, 0), (3, -1)):
            self.item(pk, quantity=quantity)
        self.item(4, quantity=10, allocated=0)
        self.item(5, quantity=10, allocated=3)
        self.assertEqual(blocked_material_ids(self.conn), {1, 2, 3})

    def test_explicit_manual_completion_keeps_allocation_evidence(self):
        self.item(1, match=False, quantity=None, field_complete=True)
        self.item(2, match=False, quantity=0, allocation_complete=True)
        self.item(3, unit="LENGTH", description="PIPE", field_complete=True)
        self.assertEqual(blocked_material_ids(self.conn), set())

    def test_latest_match_controls_conversion_instead_of_minimum_catalog_id(self):
        self.item(1, unit="LENGTH", description="PIPE")
        self.conn.execute("insert into catalog_catalogmatch values (10, 1, 2, '2026-09-11')")
        self.item(2, match=False, unit="LENGTH", description="PIPE")
        self.conn.execute("insert into catalog_catalogmatch values (20, 2, 2, '2026-09-01')")
        self.conn.execute("insert into catalog_catalogmatch values (21, 2, 1, '2026-09-11')")
        self.assertEqual(blocked_material_ids(self.conn), {2})

    def test_length_conversion_guard_is_applied_by_real_query(self):
        self.item(1, unit="LENGTH", description='PIPE 4" SCH80')
        self.item(2, unit="LENGTHS.", description='PIPE 4" SCH80 X 6M')
        self.item(3, unit="kg", description="PIPE")
        self.assertEqual(blocked_material_ids(self.conn), {1})


class DatafyLengthConversionParityTests(TestCase):
    """Source-parser examples cover each accepted path and rejected ambiguity."""

    def test_valid_lengths_follow_datafy_patterns_and_family_restrictions(self):
        examples = [
            ('DRL LENGTHS (10 TO 11.80METERS)', 'PIPE'),
            ('PIPE X 6M', 'PIPE'), ('IPE240 X 11,9ML S355ML', 'IPE'),
            ('ANGLE 75x75x8THK 12000ML', 'ANGLE'), ('6M X 4" PIPE', 'PIPE'),
            ('HEA 200 X 11800', 'HEA'), ('CHS 168.3 X 7.1 X 12000MM', 'CHS'),
            ('PIPE X 0001MM', 'PIPE'),
        ]
        for description, family in examples:
            with self.subTest(description=description):
                self.assertFalse(_conversion_blocks_po('LENGTH', 'm', description, family))

    def test_missing_ambiguous_or_zero_lengths_remain_blocked(self):
        examples = [
            ('', 'PIPE'), ('PIPE 4" SCH80', 'PIPE'), ('PLATE 6mmThk', 'PLATE'),
            ('PLATE 200 X 11800', 'PLATE'), ('6M X 4" PLATE', 'PLATE'),
            ('PIPE X 6MM', 'PIPE'), ('41MM CHANNEL M12 SLOT 3M SS', 'U_CHANNEL'),
            ('CHS 114 X 6.2 X 11.8MM', 'CHS'), ('PIPE X 0M X 6M', 'PIPE'),
            ('DRL LENGTHS (0 TO 12METERS) X 6M', 'PIPE'),
        ]
        for description, family in examples:
            with self.subTest(description=description):
                self.assertTrue(_conversion_blocks_po('LENGTH', 'm', description, family))

    def test_unit_normalization_and_existing_fallback_are_preserved(self):
        for unit in ('length', ' Lengths. ', 'LΕΝGTH', 'LЕНGTHS'):
            with self.subTest(unit=unit):
                self.assertTrue(_conversion_blocks_po(unit, 'm', 'PIPE', 'PIPE'))
        for unit in ('un', 'NOS', 'kg', '', 'unknown', '"LENGTH"', 'L.ENGTH'):
            with self.subTest(unit=unit):
                self.assertFalse(_conversion_blocks_po(unit, 'm', 'PIPE', 'PIPE'))
        self.assertFalse(_conversion_blocks_po('LENGTH', 'un', 'PIPE', 'PIPE'))

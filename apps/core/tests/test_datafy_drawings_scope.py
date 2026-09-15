from __future__ import annotations

from copy import deepcopy
import sqlite3
from unittest import TestCase

from apps.core.datafy_drawings_scope import (
    _is_duplicate_blank_table,
    supply_scope_exclusions,
)


class DatafyDrawingScopeTests(TestCase):
    """Exercise real SELECTs against an isolated, minimal source schema."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            create table core_document (
                id integer primary key, project_id integer, drawing_number text,
                revision text, uploaded_at text, status text, processed_at text,
                extraction_method text
            );
            create table core_extractedtable (
                id integer primary key, document_id integer, name text, page_number integer
            );
            create table core_materialitem (
                id integer primary key, table_id integer, item_number text,
                description text, quantity numeric, unit text, row_order integer
            );
        """)

    def document(self, pk, *, drawing="DWG-1000-00001", revision="A01", uploaded="2026-09-01",
                 project=1, status="uploaded", processed=None, method="", material=True):
        self.conn.execute("insert into core_document values (?, ?, ?, ?, ?, ?, ?, ?)",
                          (pk, project, drawing, revision, uploaded, status, processed, method))
        if material:
            self.table(pk * 10, pk)
            self.item(pk * 100, pk * 10)

    def table(self, pk, document_id, *, name="MATERIAL LIST", page=1):
        self.conn.execute("insert into core_extractedtable values (?, ?, ?, ?)",
                          (pk, document_id, name, page))

    def item(self, pk, table_id, *, number="1", description="PIPE ASTM A106 GR B SCH 80",
             quantity=12, unit="m", order=1):
        self.conn.execute("insert into core_materialitem values (?, ?, ?, ?, ?, ?, ?)",
                          (pk, table_id, number, description, quantity, unit, order))

    def test_revision_lifecycle_outranks_latest_upload(self):
        self.document(1, revision="C01", uploaded="2026-08-01")
        self.document(2, revision="R99", uploaded="2026-09-01")
        self.document(3, revision="B99", uploaded="2026-09-02")
        self.document(4, revision="A99", uploaded="2026-09-03")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], {2, 3, 4})

    def test_normalized_revision_uses_upload_then_id_for_ties(self):
        self.document(1, revision="C2", uploaded="2026-09-01")
        self.document(2, revision="Rev. c02", uploaded="2026-09-02")
        self.document(3, revision="C 02", uploaded="2026-09-02")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], {1, 2})

    def test_numeric_and_unknown_revisions_follow_source_order(self):
        self.document(1, revision="")
        self.document(2, revision="ISSUED")
        self.document(3, revision="9")
        self.document(4, revision="010")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], {1, 2, 3})

    def test_drawing_identity_normalizes_case_and_whitespace(self):
        self.document(1, drawing=" dwg\t 1000-00001 ", revision="A01")
        self.document(2, drawing="DWG 1000-00001", revision="A02")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], {1})

    def test_full_drawing_identity_and_project_are_not_merged(self):
        self.document(1, drawing="DWG-PIPING-1000-00001")
        self.document(2, drawing="DWG-STRUCTURE-1000-00001", revision="C02")
        self.document(3, drawing="DWG-PIPING-1000-00001", revision="C02", project=2)
        self.document(4, drawing="")
        self.document(5, drawing="  ", revision="C02")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], set())

    def test_unprocessed_higher_revision_does_not_hide_extracted_materials(self):
        self.document(1)
        self.document(2, revision="C01", material=False)
        self.document(3, revision="C02", material=False, status="success")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], set())

    def test_completed_zero_material_revision_supersedes_prior_scope(self):
        self.document(1)
        self.document(2, revision="C01", material=False, status="success", processed="2026-09-02")
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], {1})

    def test_reviewed_empty_extraction_and_unprocessed_upload_are_retained(self):
        self.document(1)
        self.document(2, revision="C01", material=False, status="review", method="ai-vision")
        self.document(3, revision="C02", material=False)
        self.assertEqual(supply_scope_exclusions(self.conn)["document_ids"], {1})

    def test_duplicate_blank_table_is_excluded_only_on_same_document_page(self):
        self.document(1)
        self.table(11, 1, name="\t ")
        self.item(110, 11, description="pipe  ASTM A106 GR B SCH 80", quantity=12.0)
        self.table(12, 1, name="", page=2)
        self.item(120, 12)
        self.document(2, drawing="OTHER", material=False)
        self.table(20, 2, name="")
        self.item(200, 20)
        self.assertEqual(supply_scope_exclusions(self.conn)["table_ids"], {11})

    def test_distinct_unnamed_demand_and_named_tables_remain(self):
        self.document(1)
        self.table(11, 1, name="")
        self.item(110, 11, number="50", description="SPIRAL WOUND GASKET CL150")
        self.table(12, 1, name="SECOND MATERIAL LIST")
        self.item(120, 12)
        self.assertEqual(supply_scope_exclusions(self.conn)["table_ids"], set())

    def test_matching_cannot_reuse_one_named_row_for_two_blank_rows(self):
        self.document(1)
        self.table(11, 1, name="")
        self.item(110, 11)
        self.item(111, 11, order=2)
        self.assertEqual(supply_scope_exclusions(self.conn)["table_ids"], set())

    def test_source_partial_description_heuristic_requires_matching_item_keys(self):
        named = [dict(item_number=str(i), quantity=12, unit="m", description=f"PIPE ASTM A106 SIZE {i}")
                 for i in range(5)]
        blank = deepcopy(named)
        blank[-1]["description"] = "UNREADABLE"
        self.assertTrue(_is_duplicate_blank_table(blank, named))
        blank[-1]["item_number"] = "99"
        self.assertFalse(_is_duplicate_blank_table(blank, named))

    def test_no_candidate_pages_avoids_reading_material_descriptions(self):
        self.document(1)
        statements = []
        self.conn.set_trace_callback(statements.append)
        self.assertEqual(supply_scope_exclusions(self.conn), {"document_ids": set(), "table_ids": set()})
        self.assertEqual(len(statements), 2)
        self.assertTrue(all(query.lstrip().lower().startswith("select") for query in statements))

    def test_candidate_pages_only_and_read_only_source_access(self):
        self.document(1)
        self.table(11, 1, name="")
        self.item(110, 11)
        self.table(12, 1, name="MATERIAL LIST", page=2)
        self.item(120, 12)
        statements = []
        self.conn.set_trace_callback(statements.append)
        self.assertEqual(supply_scope_exclusions(self.conn)["table_ids"], {11})
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(query.lstrip().lower().startswith("select") for query in statements))
        self.assertIn("table_id in (10, 11)", statements[-1])

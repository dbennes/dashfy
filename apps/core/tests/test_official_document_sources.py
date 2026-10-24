"""Real source SELECTs: Preparing demand is hidden but its stock stays reserved."""
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import fabrication_source, real_sources, skyline_material_source
from apps.core.release_scope import release_scope_context
from apps.core.rundown_discipline_source import _STRUCTURAL_PACKAGES_SQL
from apps.core.skyline_aveon_source import _PACKAGES_SQL as AVEON_PACKAGES_SQL


class SqliteSourceCursor:
    """Adapt the two PostgreSQL expressions used by these isolated SELECTs."""
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, query, params=()):
        query = re.sub(r"= any\(\?\)", "in (select value from json_each(?))", query)
        query = re.sub(r"string_agg\(distinct nullif\(po.po_number, ''\), ', '\)",
                       "group_concat(distinct nullif(po.po_number, ''))", query)
        params = tuple(json.dumps(value) if isinstance(value, list) else value for value in params)
        self.cursor.execute(query, params)
        return self

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()


class SqliteSourceConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return SqliteSourceCursor(self.connection)


class OfficialDocumentSourceTests(SimpleTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("greatest", -1, max)
        self.addCleanup(self.db.close)
        self.conn = SqliteSourceConnection(self.db)
        self.db.executescript("""
            create table core_document (
                id integer primary key, project_id integer, drawing_number text, title text,
                original_filename text, revision text, revision_detail text, discipline text,
                status text, priority integer, uploaded_at text, processed_at text,
                release_status text, piping_line_number text, field_complete boolean,
                field_complete_at text
            );
            create table core_extractedtable (
                id integer primary key, document_id integer, name text, page_number integer,
                "order" integer
            );
            create table core_materialitem (
                id integer primary key, table_id integer, row_order integer, item_number text,
                material_code text, extra_fields text, description text, unit text, quantity numeric
            );
            create table catalog_catalogmatch (material_item_id integer, catalog_item_id integer);
            create table catalog_catalogitem (id integer primary key);
            create table catalog_stockpiece (
                id integer primary key, catalog_item_id integer, remaining_qty numeric,
                original_qty numeric, po_item_id integer
            );
            create table catalog_allocation (
                id integer primary key, material_item_id integer, stock_piece_id integer,
                qty_allocated numeric
            );
            create table core_purchaseorder (
                id integer primary key, po_number text, supplier_name text, status text,
                validation_score numeric, requires_manual_review boolean,
                uploaded_at text, processed_at text
            );
            create table core_purchaseorderitem (id integer primary key, purchase_order_id integer);
            create table eclic_eclicdocument (
                code text, release_status text default 'official',
                has_update boolean, needs_processing boolean
            );
            create table fabrication_fabricationpackage (
                id integer primary key, code text, name text, campaign text, discipline text,
                drawing_number text, dwg_key text, document_id integer, p6_ref text,
                travel_pack_no text, weight_tons numeric, plan_start text, plan_finish text,
                actual_start text, actual_finish text, stages text, sort_order integer,
                is_active boolean, latest_import_id integer
            );
            create table fabrication_p6import (
                id integer primary key, original_filename text, imported_at text,
                activities_total integer
            );
            create table fabrication_fabricationprogressentry (
                package_id integer, progress_date text, tons_delta numeric
            );
            insert into core_document values
                (1, 1, 'ISO-1', 'Official', 'official.pdf', 'A01', '', 'piping', 'success',
                 1, '2026-09-01', '2026-09-01', 'official', '4"-LO-403236-40S-SS-P', 0, null),
                (2, 1, 'ISO-1', 'Preparing', 'preparing.pdf', 'C03', '', 'piping', 'review',
                 2, '2026-10-01', '2026-10-01', 'preparing', '4"-LO-403236-40S-SS-P', 0, null);
            insert into core_extractedtable values (10, 1, 'MATERIAL LIST', 1, 1),
                                                   (20, 2, 'MATERIAL LIST', 1, 1);
            insert into core_materialitem values
                (100, 10, 1, '1', 'PIPE', '{}', 'Pipe', 'm', 5),
                (200, 20, 1, '1', 'PIPE', '{}', 'Pipe', 'm', 6);
            insert into catalog_catalogitem values (1);
            insert into catalog_catalogmatch values (100, 1), (200, 1);
            insert into catalog_stockpiece values (1, 1, 4, 10, 1);
            insert into catalog_allocation values (1, 200, 1, 6);
            insert into core_purchaseorder values
                (1, 'PO-1', 'Supplier', 'success', 100, 0, '2026-09-01', '2026-09-01');
            insert into core_purchaseorderitem values (1, 1);
            insert into fabrication_fabricationpackage
                (id, code, discipline, document_id, drawing_number, is_active, sort_order)
                values (1, 'PKG-1', 'piping', 1, 'ISO-1', 1, 1),
                       (2, 'PKG-2', 'piping', 2, 'ISO-1', 1, 2),
                       (3, 'P6-ONLY', 'piping', null, 'ISO-P6', 1, 3);
            insert into fabrication_fabricationprogressentry values
                (1, '2026-09-04', 2), (2, '2026-09-04', 9), (3, '2026-09-04', 1);
            insert into fabrication_p6import values (1, 'P6.xlsx', '2026-09-01', 30);
            update fabrication_fabricationpackage set latest_import_id = 1;
        """)

    def rows(self, query, params=()):
        return real_sources._rows(self.conn.cursor(), query, params)

    def test_dashboard_counts_and_document_choices_only_include_official(self):
        with patch.object(real_sources, "_datafy_conn", return_value=nullcontext(self.conn)):
            dashboard = real_sources._datafy_dashboard()
            documents = real_sources._datafy_documents("", "", "", "", "", 500)
        self.assertEqual(dashboard["kpis"]["documents"], 1)
        self.assertEqual(dashboard["kpis"]["materials"], 1)
        self.assertEqual(dashboard["kpis"]["covered_materials"], 0)
        self.assertEqual(dashboard["kpis"]["allocations"], 0)
        self.assertEqual(documents["total"], 1)
        self.assertEqual([row["id"] for row in documents["rows"]], [1])
        self.assertEqual([row["value"] for row in documents["choices"]["revisions"]], ["A01"])

    def test_preparing_reservation_is_unavailable_to_official_material(self):
        rows = self.rows(fabrication_source._COVERAGE_ITEMS_SQL, ([1, 2], [1, 2]))
        self.assertEqual([row["document_id"] for row in rows], [1])
        self.assertEqual(rows[0]["stock_free_qty"], 4)
        self.assertEqual(rows[0]["allocated_qty"], 0)
        self.assertEqual(rows[0]["missing_qty"], 5)

    def test_purchase_order_totals_include_unlinked_orders_once_in_every_scope(self):
        # PO-1 serves both drawing families. PO-2 has no drawing allocation.
        self.db.execute("insert into catalog_allocation values (2, 100, 1, 1)")
        self.db.execute("insert into core_purchaseorder values (2, 'PO-2', 'Unlinked supplier', 'success', 100, 0, '2026-09-01', '2026-09-01')")
        self.db.execute("insert into core_purchaseorderitem values (2, 2)")
        for scope in ("official", "preparing", "all"):
            with self.subTest(scope=scope), release_scope_context(scope):
                self.assertEqual(real_sources._datafy_po_totals(self.conn.cursor()), {"orders": 2, "items": 2})
                with patch.object(real_sources, "_datafy_conn", return_value=nullcontext(self.conn)):
                    dashboard = real_sources._datafy_dashboard()
                self.assertEqual(dashboard["kpis"]["pos"], 2)
                self.assertEqual(dashboard["kpis"]["po_items"], 2)

    def test_fabrication_filters_preparing_and_keeps_unlinked_p6_scope(self):
        self.assertEqual([row["id"] for row in self.rows(fabrication_source._PACKAGE_SQL)], [1, 3])
        self.assertEqual(self.rows(fabrication_source._PACKAGE_ONE_SQL, (2,)), [])
        self.assertEqual(self.rows(fabrication_source._PROGRESS_SQL)[0]["total"], 3)
        self.assertEqual([row["id"] for row in self.rows(AVEON_PACKAGES_SQL)], [1, 3])
        last_import = self.rows(fabrication_source._IMPORT_SQL)[0]
        self.assertEqual(last_import["packages_total"], 2)
        self.assertEqual(last_import["packages_linked"], 1)
        self.db.execute("update fabrication_fabricationpackage set discipline = 'structural'")
        self.assertEqual([row["id"] for row in self.rows(_STRUCTURAL_PACKAGES_SQL)], [1, 3])

    def test_preparing_revision_never_hides_official_skyline_material_scope(self):
        rows = self.rows(skyline_material_source._DOCUMENTS_SQL)
        self.assertEqual([row["document_id"] for row in rows], [1])

    def test_missing_migration_returns_unavailable_without_unfiltered_retry(self):
        self.db.execute("alter table core_document rename column release_status to old_release_status")
        with patch.object(real_sources, "_datafy_conn", return_value=nullcontext(self.conn)):
            payload = real_sources.datafy_dashboard()
        self.assertFalse(payload["available"])
        self.assertIn("release_status", payload["error"])
        self.assertEqual(payload["rows"], [])

    def test_all_authorized_scopes_select_only_their_rows_and_share_reserved_stock(self):
        for scope, document_ids, package_ids, allocations, progress in [
            ("official", [1], [1, 3], 0, 3),
            ("preparing", [2], [2], 1, 9),
            ("all", [1, 2], [1, 2, 3], 1, 12),
        ]:
            with self.subTest(scope=scope), release_scope_context(scope):
                with patch.object(real_sources, "_datafy_conn", return_value=nullcontext(self.conn)):
                    dashboard = real_sources._datafy_dashboard()
                    documents = real_sources._datafy_documents("", "", "", "", "", 500)
                self.assertEqual(dashboard["kpis"]["documents"], len(document_ids))
                self.assertEqual(dashboard["kpis"]["allocations"], allocations)
                self.assertEqual(sorted(row["id"] for row in documents["rows"]), document_ids)
                self.assertTrue(all("release_status" in row for row in documents["rows"]))
                materials = self.rows(fabrication_source._COVERAGE_ITEMS_SQL, ([1, 2], [1, 2]))
                self.assertEqual(sorted(row["document_id"] for row in materials), document_ids)
                self.assertTrue(all(row["stock_free_qty"] == 4 for row in materials))
                self.assertEqual([row["id"] for row in self.rows(fabrication_source._PACKAGE_SQL)], package_ids)
                self.assertEqual(self.rows(fabrication_source._PROGRESS_SQL)[0]["total"], progress)
                self.assertEqual([row["id"] for row in self.rows(AVEON_PACKAGES_SQL)], package_ids)
                skyline_docs = self.rows(skyline_material_source._DOCUMENTS_SQL)
                self.assertEqual([row["document_id"] for row in skyline_docs], document_ids)

    def test_non_official_scope_never_uses_official_workbook_total(self):
        for scope in ("preparing", "all"):
            with release_scope_context(scope):
                reader = lambda *_: self.fail("Official workbook totals must not be queried")
                self.assertEqual(fabrication_source._weekly_progress_report_rows(object(), reader), [])

    def test_orphan_packages_use_exact_release_identity_and_keep_unknown_planning(self):
        self.db.execute("insert into core_document select 3, project_id, 'PREP-ONLY', title, original_filename, revision, revision_detail, discipline, status, priority, uploaded_at, processed_at, release_status, piping_line_number, field_complete, field_complete_at from core_document where id=2")
        self.db.execute("insert into core_document select 4, project_id, 'OFF-ONLY', title, original_filename, revision, revision_detail, discipline, status, priority, uploaded_at, processed_at, release_status, piping_line_number, field_complete, field_complete_at from core_document where id=1")
        self.db.executescript("""
            insert into fabrication_fabricationpackage
                (id, code, discipline, document_id, drawing_number, is_active, sort_order)
                values (4, 'ORPHAN-PREP', 'piping', null, 'prep-only', 1, 4),
                       (5, 'ORPHAN-OFFICIAL', 'piping', null, 'OFF-ONLY', 1, 5),
                       (6, 'AMBIGUOUS', 'piping', null, 'ISO-1', 1, 6),
                       (7, 'BLANK-P6', 'piping', null, '', 1, 7);
        """)
        for scope, expected in [("official", [1, 3, 5, 7]), ("preparing", [2, 4]),
                                ("all", [1, 2, 3, 4, 5, 6, 7])]:
            with self.subTest(scope=scope), release_scope_context(scope):
                rows = self.rows(fabrication_source._PACKAGE_SQL)
                self.assertEqual([row["id"] for row in rows], expected)
                by_id = {row["id"]: row for row in rows}
                if 4 in by_id:
                    self.assertEqual(by_id[4]["release_status"], "preparing")
                if 6 in by_id:
                    self.assertIsNone(by_id[6]["release_status"])
                if 7 in by_id:
                    self.assertEqual(by_id[7]["release_status"], "official")


class OfficialSnapshotFallbackTests(SimpleTestCase):
    def test_only_snapshots_generated_with_official_scope_are_accepted(self):
        for marker, available in [(None, False), ("official-v1", False), ("official-v2", True)]:
            with self.subTest(marker=marker):
                snapshot = SimpleNamespace(
                    pk=1, payload={"available": True, "drawing_release_scope": marker},
                    filters={"release_scope": "official", "release_scope_version": 1},
                    created_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    source_database="DATAFY", source_host="postgres:5432",
                )
                with patch.object(real_sources, "_construction_datafy", side_effect=RuntimeError("offline")), \
                     patch.object(real_sources.DatafySupplySnapshot.objects, "filter") as snapshots:
                    snapshots.return_value.order_by.return_value.first.return_value = snapshot
                    payload = real_sources._construction_datafy_snapshot({})
                self.assertEqual(payload["available"], available)
                self.assertEqual(payload["source_mode"], "postgres_snapshot" if available else "postgres_unavailable")

    def test_other_scope_and_legacy_snapshot_metadata_never_fall_back(self):
        for requested in ("official", "preparing", "all"):
            for stored in ("official", "preparing", "all", None):
                with self.subTest(requested=requested, stored=stored), release_scope_context(requested):
                    snapshot = SimpleNamespace(
                        pk=1, payload={"available": True, "drawing_release_scope": f"{stored}-v2"},
                        filters={"release_scope": stored, "release_scope_version": 1} if stored else {},
                        created_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                        source_database="DATAFY", source_host="postgres:5432",
                    )
                    with patch.object(real_sources, "_construction_datafy", side_effect=RuntimeError("offline")), \
                         patch.object(real_sources.DatafySupplySnapshot.objects, "filter") as snapshots:
                        snapshots.return_value.order_by.return_value.first.return_value = snapshot
                        payload = real_sources._construction_datafy_snapshot({})
                    self.assertEqual(payload["available"], requested == stored)

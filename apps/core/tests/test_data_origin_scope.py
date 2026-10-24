"""Preparing applies to DATAFY drawings, not external engineering registers."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.core import real_sources as sources
from apps.core.dashboard_cache import fresh_sources
from apps.core.models import EngineeringDocumentStatus, EngineeringMonitorImport, EngineeringStatusImport
from apps.core.release_scope import release_scope_context


class ExternalEngineeringScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.numbers = ("DRAWING-OFFICIAL-IN-DATAFY", "DRAWING-PREPARING-IN-DATAFY")
        docs = [{"document_number": number, "title": number, "discipline": "PIPING",
                 "revision": "C01", "revision_family": "C", "status_bucket": "AFC 1",
                 "document_status_effective": "ISSUED", "is_monitored": True, "is_countable": True}
                for number in cls.numbers]
        EngineeringMonitorImport.objects.create(
            original_filename="external-MDR.xlsx", file_hash="external-mdr", document_count=2,
            monitored_document_count=2, discipline_count=1, excluded_count=0,
            metadata={"import_mode": "mdr_engineering"}, payload={"documents": docs},
        )
        ded = EngineeringStatusImport.objects.create(
            original_filename="external-DED.xlsx", file_hash="external-ded", document_count=2,
            discipline_count=1,
        )
        for row_number, number in enumerate(cls.numbers, 2):
            EngineeringDocumentStatus.objects.create(
                import_batch=ded, row_number=row_number, document_number=number,
                title=number, discipline="PIPING", revision="C01", revision_family="C",
                doc_status="AFC", doc_status_group="AFC", afc_code="1", document_status="ISSUED",
            )

    def setUp(self):
        cache.clear()

    def test_mdr_and_ded_totals_stay_equal_without_any_datafy_read(self):
        for scope in ("official", "preparing", "all"):
            with self.subTest(scope=scope), release_scope_context(scope), \
                 patch.object(sources, "_datafy_conn", side_effect=AssertionError("External register must not read DATAFY")) as datafy:
                filters = sources._construction_filters({})
                monitor = sources._engineering_monitor_from_snapshot(filters)
                ded = sources._engineering_from_ded_snapshot(filters)
            self.assertEqual(monitor["flow"]["total"], 2)
            self.assertEqual(monitor["raw_document_count"], 2)
            self.assertEqual(monitor["error"], "")
            self.assertEqual({doc["document_number"] for doc in monitor["documents"]}, set(self.numbers))
            self.assertEqual(ded["engineering_docs"], 2)
            self.assertEqual({doc["codigo"] for doc in ded["engineering_documents"]}, set(self.numbers))
            datafy.assert_not_called()

    def test_external_eclic_api_keeps_its_register_in_every_drawing_scope(self):
        api_rows = [{"Code": number, "Title": number, "Discipline": "MP - PIPING",
                     "Revision": "C01", "DocumentStatus": "ISSUED"}
                    for number in self.numbers]
        for scope in ("official", "preparing", "all"):
            with self.subTest(scope=scope), release_scope_context(scope), \
                 patch.object(sources, "_eclic_documents_from_api", return_value=api_rows), \
                 patch.object(sources, "_datafy_conn", side_effect=AssertionError("External API must not read DATAFY")) as datafy:
                result = sources._engineering_from_eclic_api(sources._construction_filters({}))
            self.assertEqual(result["engineering_docs"], 2)
            self.assertEqual({doc["codigo"] for doc in result["engineering_documents"]}, set(self.numbers))
            datafy.assert_not_called()

    def test_datafy_outage_preserves_mdr_indicators_in_the_cockpit(self):
        for scope in ("official", "preparing", "all"):
            with self.subTest(scope=scope), release_scope_context(scope), fresh_sources(), \
                 patch.object(sources, "_p6_dashboard", return_value={"available": False, "kpis": {}, "charts": {}}), \
                 patch.object(sources, "_construction_taskfy", side_effect=RuntimeError("Taskfy offline")), \
                 patch.object(sources, "_construction_datafy", side_effect=RuntimeError("DATAFY offline")), \
                 patch.object(sources, "_datafy_conn", side_effect=AssertionError("No source connection is allowed")) as datafy:
                result = sources.management_dashboard({})
            self.assertEqual(result["construction"]["kpis"]["engineering_docs"], 2)
            self.assertEqual(result["construction"]["engineering_error"], "")
            self.assertFalse(result["material"]["available"])
            datafy.assert_not_called()

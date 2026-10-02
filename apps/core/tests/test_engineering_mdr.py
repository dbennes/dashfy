from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from apps.core.engineering_monitor_import import MDR_SOURCE, _mdr_status, import_engineering_monitor_workbook
from apps.core.engineering_mdr_summary import MDR_STATUSES, mdr_scope_summaries
from apps.core.models import EngineeringMonitorImport
from apps.core.real_sources import _construction_engineering_fallback, _engineering_monitor_from_snapshot


def mdr_upload(statuses=("AFC/AFU RETURNED AS CODE 1", "Missing Issue Code Status"), *, current_header=True):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "FOE MDR"
    sheet.append(["FOE MDR"])
    sheet.append([
        "MABU DOC NUMBER", "DOCUMENT TITLE", "DISCIPLINE",
        "Rev. Status On DED Completion (July 2026)", "Code Status On DED Completion",
        "Rev. Status 30th Sept", "Code Status 30th Sept" if current_header else "Unknown status",
        "Document Status", "ENG. CATEGORY",
    ])
    for index, status in enumerate(statuses):
        sheet.append([
            f"DOC-{index}", "TEST DOCUMENT", "Piping Engineering\n(Isometrics)",
            "R01", "Pending First Issue", "C02", status, "DOCUMENT FINALIZED UNDER FOE", "CAT 0/1" if index == 0 else "CAT 3",
        ])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return SimpleUploadedFile("FOE MDR.xlsx", stream.getvalue())


class MdrCodeStatusTests(SimpleTestCase):
    def test_code_status_mapping_preserves_ambiguity_and_return_codes(self):
        for source, expected in [
            ("AFC/AFU RETURNED AS CODE 1\n(No Workflow Started)", "AFC 1"),
            ("AFC/AFU RETURNED AS CODE 3", "AFC 3"),
            ("AFC/AFU RETURNED AS CODE 3A", "AFC CODE 3A"),
            ("AFC/AFU RETURNED AS CODE 4", "REJECTED"),
            ("AFC/AFU RETURNED AS CODE 10", "UNCLASSIFIED"),
            ("Missing Issue Code Status", "UNCLASSIFIED"),
            ("", "UNCLASSIFIED"),
            ("Pending First Issue", "NI"),
            ("IFR RETURNED AS CODE 3", "IFR"),
            ("IFA RETURNED AS CODE 1", "IFA"),
            ("FOE Workflow in Progress (Engineering Check)", "UNDER REVIEW"),
            ("Under Review (DED)", "UNDER REVIEW"),
            ("ISSUED FOR INFORMATION AS CODE 5", "IFI"),
        ]:
            with self.subTest(source=source):
                self.assertEqual(_mdr_status(source), expected)


class MdrImportTests(TestCase):
    def test_initial_command_imports_workbook_and_preserves_future_uploads(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "FOE MDR.xlsx"
            path.write_bytes(mdr_upload().read())
            call_command("import_engineering_mdr", str(path), initial_only=True, verbosity=0)
            first = EngineeringMonitorImport.objects.get(is_active=True)
            self.assertEqual(first.document_count, 2)
            newer = import_engineering_monitor_workbook(mdr_upload(("Pending First Issue",)), require_mdr=True)
            call_command("import_engineering_mdr", str(path), initial_only=True, verbosity=0)
            self.assertEqual(EngineeringMonitorImport.objects.get(is_active=True), newer)
            self.assertEqual(EngineeringMonitorImport.objects.count(), 2)

    def test_current_columns_and_all_documents_feed_same_dashboard_source(self):
        batch = import_engineering_monitor_workbook(mdr_upload(), require_mdr=True)
        self.assertEqual(batch.document_count, 2)
        self.assertEqual(batch.monitored_document_count, 2)
        self.assertEqual(batch.metadata["source_label"], MDR_SOURCE)
        self.assertEqual(batch.metadata["source_columns"]["status_column"], "CODE STATUS 30TH SEPT")
        self.assertEqual([row["revision"] for row in batch.payload["documents"]], ["C02", "C02"])
        self.assertEqual(batch.payload["documents"][0]["discipline"], "PIPING ISOMETRIC")
        self.assertEqual(batch.metadata["status_counts"], {"AFC 1": 1, "UNCLASSIFIED": 1})
        with patch("apps.core.real_sources._engineering_from_eclic_api") as eclic:
            result = _construction_engineering_fallback({}, "Taskfy offline")
        eclic.assert_not_called()
        self.assertEqual(result["engineering_flow"]["total"], 2)
        self.assertEqual(result["engineering_flow"]["afc"], 1)
        self.assertEqual(result["engineering_source"], MDR_SOURCE)
        self.assertEqual(result["engineering_flow"], result["engineering_monitor"]["flow"])

    def test_invalid_import_preserves_active_batch_and_valid_import_replaces_it(self):
        original = import_engineering_monitor_workbook(mdr_upload(), require_mdr=True)
        with self.assertRaisesMessage(ValueError, "current CODE STATUS"):
            import_engineering_monitor_workbook(mdr_upload(current_header=False), require_mdr=True)
        original.refresh_from_db()
        self.assertTrue(original.is_active)
        replacement = import_engineering_monitor_workbook(mdr_upload(("Pending First Issue",)), require_mdr=True)
        original.refresh_from_db()
        self.assertFalse(original.is_active)
        self.assertEqual(list(EngineeringMonitorImport.objects.filter(is_active=True)), [replacement])

    def test_missing_import_does_not_fall_back_to_eclic(self):
        with patch("apps.core.real_sources._engineering_from_eclic_api") as eclic:
            result = _construction_engineering_fallback({}, "Taskfy offline")
        eclic.assert_not_called()
        self.assertEqual(result["engineering_flow"]["total"], 0)
        self.assertEqual(result["engineering_source_mode"], "postgres_import_missing")

    def test_warning_precedes_both_columns_and_includes_import_provenance(self):
        import_engineering_monitor_workbook(mdr_upload(), require_mdr=True)
        monitor = _engineering_monitor_from_snapshot({})
        html = render_to_string("core/home.html", {"manager": {"construction": {"engineering_monitor": monitor}}})
        self.assertIn("MDR spreadsheet provided by Engineering", html)
        self.assertIn("This information no longer comes from eClic.", html)
        self.assertIn("Last dashboard update:", html)
        self.assertIn("FOE MDR.xlsx", html)
        self.assertIn("Classification: Document Status", html)
        self.assertLess(html.index('class="c3-engineering-warning"'), html.index('class="row-2 c3-engineering-layout"'))

    def test_import_keeps_category_and_summary_uses_document_status(self):
        batch = import_engineering_monitor_workbook(mdr_upload(), require_mdr=True)
        self.assertEqual(batch.payload["documents"][0]["engineering_category"], "CAT 0/1")
        overall, fabrication = _engineering_monitor_from_snapshot({})["mdr_scopes"]
        self.assertEqual((overall["total"], fabrication["total"]), (2, 1))
        self.assertEqual((overall["finalized"], fabrication["finalized"]), (2, 1))


class MdrScopeSummaryTests(SimpleTestCase):
    def test_scope_totals_status_columns_and_discipline_totals_reconcile(self):
        docs = [
            {"document_status_original": label, "discipline": "PIPING", "engineering_category": category}
            for _tone, label in MDR_STATUSES
            for category in ("CAT 0/1", "CAT 2", "CAT 3", "Procurement")
        ]
        overall, fabrication = mdr_scope_summaries(docs, ["PIPING"])
        self.assertEqual((overall["total"], fabrication["total"]), (32, 16))
        for scope in (overall, fabrication):
            self.assertEqual(sum(row["value"] for row in scope["status_rows"]), scope["total"])
            self.assertEqual(sum(scope["discipline_rows"][0]["status_cells"][i]["value"] for i in range(8)), scope["total"])
            self.assertTrue(all(row["pct"] == 12.5 for row in scope["status_rows"]))
            self.assertEqual([row["label"] for row in scope["status_rows"]], [label for _, label in MDR_STATUSES])

    def test_zero_statuses_unknown_statuses_and_missing_categories_are_explicit(self):
        scopes = mdr_scope_summaries([{"document_status_original": "NEW STATUS", "discipline": "PIPING"}], ["PIPING"])
        self.assertEqual(len(scopes[0]["status_rows"]), 9)
        self.assertEqual(scopes[0]["status_rows"][-1]["value"], 1)
        self.assertEqual(scopes[0]["status_rows"][3]["value"], 0)
        self.assertFalse(scopes[1]["available"])
        self.assertEqual(scopes[1]["total_pct"], 0)

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.engineering_monitor_import import (
    MONITOR_SAMPLE_EXCLUDED_FOLDERS,
    _monitor_sample_gate,
    _parse_monitor_rows,
    _parse_official_rows,
    _status_payload,
)


class _Worksheet:
    def __init__(self, rows):
        self._rows = rows
        self.max_row = len(rows)

    def iter_rows(self, **_kwargs):
        yield from self._rows


class EngineeringMonitorSampleGateTests(SimpleTestCase):
    def test_includes_ded_and_foe_descendants(self):
        self.assertEqual(
            _monitor_sample_gate("BNO / 02-DED / 02.17-MP-PIPING", "ISSUED"),
            (True, ""),
        )
        self.assertEqual(
            _monitor_sample_gate("BNO / 02.5-FOE / FOE.05-CS-STRUCTURAL", "ISSUED"),
            (True, ""),
        )

    def test_normalizes_case_spacing_nbsp_and_backslashes(self):
        self.assertEqual(
            _monitor_sample_gate(" bno\u00a0\\ 02-ded \\ 02.17-mp-piping ", "issued"),
            (True, ""),
        )

    def test_excludes_every_configured_folder_and_its_descendants(self):
        for folder in MONITOR_SAMPLE_EXCLUDED_FOLDERS:
            with self.subTest(folder=folder):
                self.assertEqual(
                    _monitor_sample_gate(folder, "ISSUED"),
                    (False, "Excluded sample folder"),
                )
                self.assertEqual(
                    _monitor_sample_gate(f"{folder} / CHILD", "ISSUED"),
                    (False, "Excluded sample folder"),
                )

    def test_does_not_exclude_a_similarly_named_sibling(self):
        self.assertEqual(
            _monitor_sample_gate(
                "BNO / 02-DED / 02.300-DAE_PROCUREMENT-ARCHIVE",
                "ISSUED",
            ),
            (True, ""),
        )

    def test_excludes_paths_outside_the_two_roots(self):
        self.assertEqual(
            _monitor_sample_gate("BNO / 03-VENDOR / POWELL", "ISSUED"),
            (False, "Outside configured sample folders"),
        )

    def test_accepts_portuguese_and_english_cancelled_statuses(self):
        for status in ("CANCELED", "CANCELLED", "CANCELADO", "CANCELADA", " cancelado "):
            with self.subTest(status=status):
                self.assertEqual(
                    _monitor_sample_gate("BNO / 02-DED / 02.17-MP-PIPING", status),
                    (False, "Cancelled document status"),
                )

        self.assertEqual(
            _monitor_sample_gate(
                "BNO / 02-DED / 02.17-MP-PIPING",
                "CANCEL REQUESTED",
            ),
            (True, ""),
        )


class EngineeringMonitorPopulationTests(SimpleTestCase):
    @staticmethod
    def _payload(**overrides):
        values = {
            "document_status": "ISSUED",
            "issue_status": "ISSUED FOR INFORMATION AS CODE 5",
            "last_transmittal_purpose": "",
            "fabrication_ref": "",
            "directory": "BNO / 02-DED / 02.17-MP-PIPING",
            "document_number": "BNO-MABU-PVN-LT-8502",
            "revision": "X",
            "title": "MONTHLY RISK / 3D MODEL REVIEW FILE",
        }
        values.update(overrides)
        return _status_payload(**values)

    def test_legacy_document_title_and_revision_rules_no_longer_reduce_sample(self):
        result = self._payload()

        self.assertTrue(result["is_in_sample"])
        self.assertTrue(result["is_countable"])
        self.assertEqual(result["status_bucket"], "IFI")

    def test_not_applicable_and_unmapped_rows_remain_in_sample(self):
        not_applicable = self._payload(
            document_status="NÃO SE APLICA",
            issue_status="",
        )
        unclassified = self._payload(
            document_status="DESIGN START",
            issue_status="",
        )

        self.assertTrue(not_applicable["is_countable"])
        self.assertEqual(not_applicable["status_bucket"], "N/A")
        self.assertTrue(unclassified["is_countable"])
        self.assertEqual(unclassified["status_bucket"], "UNCLASSIFIED")

    def test_raw_parser_keeps_a_sampled_discipline_outside_old_whitelist(self):
        headers = (
            "Document Number",
            "Title",
            "Discipline",
            "Revision",
            "Directory",
            "Document Status",
            "Issue Status",
            "Last transmittal purpose",
        )
        worksheet = _Worksheet([
            headers,
            (
                "BNO-MABU-300-QA-5798-10001",
                "QUALITY DOCUMENT",
                "QA - QUALITY",
                "A01",
                "BNO / 02-DED / 02.24-QA-QUALITY",
                "ISSUED",
                "APPROVED FOR USE AS CODE 1",
                "",
            ),
        ])

        rows = _parse_monitor_rows(worksheet)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_monitored"])
        self.assertTrue(rows[0]["is_countable"])
        self.assertEqual(rows[0]["discipline"], "QA - QUALITY")

    def test_official_base_keeps_contabilizar_as_authoritative_without_status(self):
        worksheet = _Worksheet([
            ("Documento", "Contabilizar", "Status normalizado", "Disciplina"),
            ("DOC-001", "SIM", "", "QA - QUALITY"),
        ])

        rows = _parse_official_rows(worksheet)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_in_sample"])
        self.assertTrue(rows[0]["is_countable"])

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.engineering_monitor_import import (
    MONITOR_SAMPLE_EXCLUDED_FOLDERS,
    _monitor_sample_gate,
    _parse_monitor_rows,
    _parse_official_rows,
    _status_payload,
    _worksheet_has_headers,
)


class _Worksheet:
    def __init__(self, rows):
        self._rows = rows
        self.max_row = len(rows)

    def iter_rows(self, min_row=1, max_row=None, **_kwargs):
        yield from self._rows[min_row - 1:max_row]


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

        self.assertEqual(
            _monitor_sample_gate(
                "BNO / 02-DED / 02.300-DAE_PROCUREMENT / 02.302-OTHER",
                "ISSUED",
            ),
            (True, ""),
        )

    def test_previously_excluded_folders_are_now_included(self):
        for folder in (
            "BNO / 02-DED / 02.002-MOM",
            "BNO / 02-DED / 02.005-TRANSFER",
            "BNO / 02-DED / 02.29-3D MODEL",
        ):
            with self.subTest(folder=folder):
                self.assertEqual(
                    _monitor_sample_gate(f"{folder} / CHILD", "ISSUED"),
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

    def test_excludes_configured_purpose_next_issue_values(self):
        for purpose in (
            "FORECAST",
            "FOE - RESUBMIT",
            "IFI - ISSUED FOR INFORMATION",
        ):
            with self.subTest(purpose=purpose):
                self.assertEqual(
                    _monitor_sample_gate(
                        "BNO / 02-DED / 02.17-MP-PIPING",
                        "ISSUED",
                        purpose,
                        "A01",
                    ),
                    (False, "Excluded purpose next issue"),
                )

    def test_excludes_any_revision_containing_a_dot(self):
        for revision in ("C03.1", "A06.1", ".", " R01. "):
            with self.subTest(revision=revision):
                self.assertEqual(
                    _monitor_sample_gate(
                        "BNO / 02-DED / 02.17-MP-PIPING",
                        "ISSUED",
                        "AFC/AFU - RELEASE",
                        revision,
                    ),
                    (False, "Revision contains field mark"),
                )


class EngineeringMonitorPopulationTests(SimpleTestCase):
    @staticmethod
    def _payload(**overrides):
        values = {
            "document_status": "ISSUED",
            "issue_status": "",
            "last_transmittal_purpose": "",
            "fabrication_ref": "",
            "directory": "BNO / 02-DED / 02.17-MP-PIPING",
            "document_number": "BNO-MABU-PVN-LT-8502",
            "revision": "X",
            "title": "MONTHLY RISK / 3D MODEL REVIEW FILE",
            "purpose_next_issue": "AFC/AFU - RELEASE",
            "approval_code": "",
        }
        values.update(overrides)
        return _status_payload(**values)

    def test_legacy_document_title_and_revision_rules_no_longer_reduce_sample(self):
        result = self._payload()

        self.assertTrue(result["is_in_sample"])
        self.assertTrue(result["is_countable"])
        self.assertEqual(result["status_bucket"], "AFC 1")

    def test_afc_release_and_blank_purpose_are_unconditional(self):
        direct = self._payload(
            purpose_next_issue="AFC/AFU - RELEASE",
            approval_code="CODE 4 - MAJOR COMMENTS",
        )
        blank = self._payload(
            document_status="NÃO SE APLICA",
            purpose_next_issue="",
            approval_code="",
        )

        self.assertTrue(direct["is_countable"])
        self.assertEqual(direct["status_bucket"], "AFC 1")
        self.assertTrue(blank["is_countable"])
        self.assertEqual(blank["status_bucket"], "AFC 1")

    def test_iff_requires_approval_code_one_two_or_three(self):
        for approval_code in (
            "CODE 1 - APPROVED",
            "CODE 2 - NO COMMENTS",
            "CODE 3 - MINOR COMMENTS",
        ):
            with self.subTest(approval_code=approval_code):
                result = self._payload(
                    purpose_next_issue="IFF - ISSUED FOR FABRICATION",
                    approval_code=approval_code,
                )
                self.assertTrue(result["is_countable"])
                self.assertEqual(result["status_bucket"], "AFC 1")

        for approval_code in ("", "CODE 4 - MAJOR COMMENTS", "CODE 10 - INVALID", "OVERDUE"):
            with self.subTest(approval_code=approval_code):
                excluded = self._payload(
                    purpose_next_issue="IFF - ISSUED FOR FABRICATION",
                    approval_code=approval_code,
                )
                self.assertFalse(excluded["is_countable"])
                self.assertEqual(excluded["excluded_reason"], "IFF without approved return code")

    def test_ifa_excludes_ra_7769_only_inside_ifa(self):
        excluded = self._payload(
            purpose_next_issue="IFA - ISSUED FOR APPROVAL",
            document_number="BNO-MABU-300-RA-7769-10001",
        )
        included = self._payload(
            purpose_next_issue="IFA - ISSUED FOR APPROVAL",
            document_number="BNO-MABU-300-EA-3323-10007",
        )

        self.assertFalse(excluded["is_countable"])
        self.assertEqual(excluded["excluded_reason"], "IFA RA-7769 excluded")
        self.assertTrue(included["is_countable"])
        self.assertEqual(included["status_bucket"], "IFA")

    def test_ifr_excludes_3323_only_inside_ifr(self):
        excluded = self._payload(
            purpose_next_issue="IFR - ISSUED FOR REVIEW",
            document_number="BNO-MABU-300-MP-3323-10005",
        )
        included = self._payload(
            purpose_next_issue="IFR - ISSUED FOR REVIEW",
            document_number="BNO-MABU-300-RA-7769-10008-006",
        )

        self.assertFalse(excluded["is_countable"])
        self.assertEqual(excluded["excluded_reason"], "IFR 3323 excluded")
        self.assertTrue(included["is_countable"])
        self.assertEqual(included["status_bucket"], "IFR")

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
            "Purpose Next Issue",
            "11-Cpy_Approval_Code",
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
                "AFC/AFU - RELEASE",
                "CODE 1 - APPROVED",
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

    def test_official_base_round_trip_preserves_afc_and_new_rule_fields(self):
        worksheet = _Worksheet([
            (
                "Documento",
                "Contabilizar",
                "Status normalizado",
                "Disciplina",
                "Purpose Next Issue",
                "11-Cpy_Approval_Code",
            ),
            (
                "DOC-001",
                "SIM",
                "AFC 1",
                "QA - QUALITY",
                "IFF - ISSUED FOR FABRICATION",
                "CODE 3 - MINOR COMMENTS",
            ),
        ])

        rows = _parse_official_rows(worksheet)

        self.assertEqual(rows[0]["status_bucket"], "AFC 1")
        self.assertEqual(rows[0]["doc_status_group"], "AFC")
        self.assertEqual(rows[0]["afc_code"], "1")
        self.assertEqual(rows[0]["purpose_next_issue"], "IFF - ISSUED FOR FABRICATION")
        self.assertEqual(rows[0]["approval_code"], "CODE 3 - MINOR COMMENTS")


class EngineeringMonitorWorksheetTests(SimpleTestCase):
    def test_raw_sheet_requires_new_rule_columns(self):
        legacy_sheet = _Worksheet([
            (
                "Document Number",
                "Title",
                "Discipline",
                "Revision",
                "Directory",
                "Document Status",
            ),
        ])
        complete_sheet = _Worksheet([
            (
                "Document Number",
                "Title",
                "Discipline",
                "Revision",
                "Directory",
                "Document Status",
                "Purpose Next Issue",
                "11-Cpy_Approval_Code",
            ),
        ])

        self.assertFalse(_worksheet_has_headers(legacy_sheet, {
            "Document Number",
            "Title",
            "Discipline",
            "Revision",
            "Directory",
            "Document Status",
            "Purpose Next Issue",
            "11-Cpy_Approval_Code",
        }))
        self.assertTrue(_worksheet_has_headers(complete_sheet, {
            "Document Number",
            "Title",
            "Discipline",
            "Revision",
            "Directory",
            "Document Status",
            "Purpose Next Issue",
            "11-Cpy_Approval_Code",
        }))

    def test_parser_uses_detected_header_row(self):
        worksheet = _Worksheet([
            ("Engineering monitor export",),
            (
                "Document Number",
                "Title",
                "Discipline",
                "Revision",
                "Directory",
                "Document Status",
                "Purpose Next Issue",
                "11-Cpy_Approval_Code",
            ),
            (
                "DOC-001",
                "DOCUMENT",
                "QA - QUALITY",
                "A01",
                "BNO / 02-DED / 02.24-QA-QUALITY",
                "ISSUED",
                "AFC/AFU - RELEASE",
                "",
            ),
        ])

        rows = _parse_monitor_rows(worksheet)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row_number"], 3)
        self.assertEqual(rows[0]["document_number"], "DOC-001")

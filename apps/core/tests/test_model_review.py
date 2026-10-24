from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory

from apps.core.model_review import aggregate_status, build_review, line_key, line_tags, package_state
from apps.core.release_scope import release_scope_context
from apps.core.views import model_review_view


class ModelReviewTests(SimpleTestCase):
    def test_both_keeps_each_release_family_and_its_revision_progress(self):
        official = {"id": 1, "project_id": 1, "revision": "A01", "drawing_number": "ISO-1",
                    "discipline": "piping", "piping_line_number": '4"-LO-403236-40S-SS-P',
                    "release_status": "official"}
        preparing = {**official, "id": 2, "revision": "C03", "release_status": "preparing"}
        newer_preparing = {**preparing, "id": 3, "revision": "C04"}
        packages = [{"document_id": 1, "discipline": "piping", "stages": {"welding": {"pct": 20}}},
                    {"document_id": 2, "discipline": "piping", "stages": {"welding": {"pct": 100}}}]
        for scope, expected in [("official", [("1", "started")]), ("preparing", [("3", "completed")]),
                                ("all", [("1", "started"), ("3", "completed")])]:
            with self.subTest(scope=scope), release_scope_context(scope):
                result = build_review([official, preparing, newer_preparing], packages)
                self.assertEqual([(doc["id"], doc["status"]) for doc in result["drawings"]], expected)
                self.assertTrue(all(doc["release_status"] in {"official", "preparing"} for doc in result["drawings"]))

    def test_known_preparing_orphan_recovers_only_exact_unique_preparing_drawing(self):
        document = {"id": 1, "drawing_number": "PREP-1", "release_status": "preparing",
                    "discipline": "piping", "piping_line_number": '4"-LO-403236-40S-SS-P'}
        package = {"document_id": None, "drawing_number": "PREP-1", "release_status": "preparing",
                   "discipline": "piping", "stages": {"welding": {"pct": 100}}}
        with release_scope_context("preparing"):
            self.assertEqual(build_review([document], [package])["drawings"][0]["status"], "completed")
        self.assertEqual(build_review([document], [package])["drawings"], [])

    def test_ambiguous_orphan_in_both_never_assigns_progress_between_release_families(self):
        doc = {"id": 1, "drawing_number": "ISO-1", "discipline": "piping",
               "piping_line_number": '4"-LO-403236-40S-SS-P', "release_status": "official"}
        package = {"document_id": None, "drawing_number": "ISO-1", "discipline": "piping",
                   "stages": {"welding": {"pct": 100}}}
        with release_scope_context("all"):
            result = build_review([doc, {**doc, "id": 2, "release_status": "preparing"}], [package])
        self.assertEqual([row["status"] for row in result["drawings"]], ["unlinked", "unlinked"])

    def test_preparing_never_appears_or_reconnects_progress_to_official(self):
        official = {"id": 1, "project_id": 1, "revision": "A01", "drawing_number": "ISO-1",
                    "discipline": "piping", "piping_line_number": '4"-LO-403236-40S-SS-P',
                    "release_status": "official"}
        preparing = {**official, "id": 2, "revision": "C03", "release_status": "preparing"}
        package = {"document_id": 2, "drawing_number": "ISO-1", "discipline": "piping",
                   "stages": {"welding": {"pct": 100}}}
        result = build_review([official, preparing], [package])
        self.assertEqual([doc["id"] for doc in result["drawings"]], ["1"])
        self.assertEqual(result["lines"][0]["status"], "unlinked")
        self.assertEqual(build_review([preparing], [package])["drawings"], [])

    def test_preparing_package_with_removed_link_does_not_use_number_fallback(self):
        document = {"id": 1, "drawing_number": "ISO-1", "discipline": "piping",
                    "piping_line_number": '4"-LO-403236-40S-SS-P'}
        package = {"document_id": None, "drawing_number": "ISO-1", "discipline": "piping",
                   "release_status": "preparing", "stages": {"welding": {"pct": 100}}}
        self.assertEqual(build_review([document], [package])["lines"][0]["status"], "unlinked")

    def test_missing_package_link_uses_unique_exact_current_drawing(self):
        tag = '4"-LO-403236-40S-SS-P'
        number = "BNO-MABU-300-MP-2343-10162"
        docs = [{"id": 840, "project_id": 1, "revision": "C03", "drawing_number": number,
                 "discipline": "piping", "piping_line_number": tag}]
        for progress, expected in [(60, "started"), (100, "completed")]:
            with self.subTest(progress=progress):
                package = {"document_id": None, "drawing_number": number, "discipline": "piping",
                           "stages": {"welding": {"pct": progress}}}
                result = build_review(docs, [package])
                self.assertEqual(result["lines"][0]["status"], expected)
                self.assertFalse(result["lines"][0]["unlinked"])
                self.assertEqual(result["lines"][0]["drawing_ids"], ["840"])

    def test_superseded_revision_does_not_prevent_completed_colour(self):
        docs = [{"id": pk, "project_id": 1, "revision": revision, "drawing_number": "ISO-1",
                 "discipline": "piping", "piping_line_number": '4"-LO-403236-40S-SS-P'}
                for pk, revision in [(1, "C02"), (2, "C03")]]
        for linked_id in (None, 1, 2):
            with self.subTest(linked_id=linked_id):
                result = build_review(docs, [{"document_id": linked_id, "drawing_number": "ISO-1",
                                             "discipline": "piping", "stages": {"welding": {"pct": 100}}}])
                self.assertEqual(len(result["drawings"]), 1)
                self.assertEqual(result["lines"][0]["status"], "completed")
                self.assertEqual(result["lines"][0]["drawing_ids"], ["2"])

    def test_unlinked_package_does_not_guess_project_discipline_or_partial_number(self):
        doc = {"id": 1, "project_id": 1, "revision": "C03", "drawing_number": "ISO-10162",
               "discipline": "piping", "piping_line_number": '4"-LO-403236-40S-SS-P'}
        package = {"document_id": None, "drawing_number": "ISO-10162", "discipline": "piping",
                   "stages": {"welding": {"pct": 100}}}
        for docs, pkg in [([doc, {**doc, "id": 2, "project_id": 2}], package),
                          ([doc], {**package, "discipline": "structural"}),
                          ([doc], {**package, "drawing_number": "10162"})]:
            with self.subTest(docs=docs, pkg=pkg):
                self.assertTrue(all(line["status"] == "unlinked" for line in build_review(docs, [pkg])["lines"]))

    def test_drawings_without_piping_lines_remain_in_their_discipline(self):
        docs = [{"id": 1, "drawing_number": "STR-1", "discipline": "structural", "piping_line_number": "N/A"},
                {"id": 2, "drawing_number": "ELE-1", "discipline": "electrical", "piping_line_number": ""},
                {"id": 3, "drawing_number": "INS-1", "discipline": "instrumentation", "piping_line_number": None}]
        payload = build_review(docs, [{"document_id": 1, "discipline": "structural", "stages": {"welding": {"pct": 20}}}])
        self.assertEqual([doc["discipline"] for doc in payload["drawings"]], ["structural", "electrical", "instrumentation"])
        self.assertEqual(payload["drawings"][0]["status"], "started")
        self.assertTrue(all(not doc["lines"] for doc in payload["drawings"]))
        self.assertEqual(payload["lines"], [])

    def test_status_uses_actual_progress_and_does_not_round_to_completion(self):
        self.assertEqual(package_state({}), "not_started")
        self.assertEqual(package_state({"actual_start": date(2026, 9, 1)}), "started")
        for progress, expected in [(0, "not_started"), (0.01, "started"), (99.99, "started"), (100, "completed")]:
            self.assertEqual(package_state({"stages": {"welding": {"pct": progress}}}), expected)

    def test_one_incomplete_or_unlinked_drawing_prevents_blue_line(self):
        self.assertEqual(aggregate_status(["completed", "not_started"]), "started")
        self.assertEqual(aggregate_status(["completed", "unlinked"]), "started")
        self.assertEqual(aggregate_status(["completed", "completed"]), "completed")
        self.assertEqual(aggregate_status([]), "unlinked")

    def test_fractional_sizes_preserved_and_placeholder_lines_removed(self):
        self.assertEqual(line_tags('3/4"-PM-043117-80-B; N/A\n-'), ['3/4"-PM-043117-80-B'])

    def test_numeric_class_quotes_are_optional_without_losing_tag_identity(self):
        for quoted, plain in [
            ('/4"-PG-313047-"750"-FFLT-1H', '4"-PG-313047-750-FFLT-1H'),
            ('/4"-PG-313050-"750"-FFLT-1H', '4"-PG-313050-750-FFLT-1H'),
            ('/1-1/2"-CM-423050-"281"-J2', '1-1/2"-CM-423050-281-J2'),
            ('/3/4"-CM-423050-"281"-J2/B1', '3/4"-CM-423050-281-J2/B1'),
            ('4"-PG-313050-"750"', '4"-PG-313050-750'),
        ]:
            with self.subTest(quoted=quoted):
                self.assertEqual(line_key(quoted), plain)
        canonical = line_key('4"-PG-313050-"750"-FFLT-1H')
        for distinct in ['4-PG-313050-750-FFLT-1H', '6"-PG-313050-750-FFLT-1H',
                         '4"-PG-313050-750-FFLT-2H', '4"-PG-313050-750-FFLT-1H/B1',
                         'PG-313050', '3050']:
            with self.subTest(distinct=distinct):
                self.assertNotEqual(line_key(distinct), canonical)
        for unchanged in ['4"-PG-313050-"750A"-FFLT-1H', '4"-PG-313050-"750-FFLT-1H',
                          '4"-PG-313050-750"-FFLT-1H']:
            with self.subTest(unchanged=unchanged):
                self.assertEqual(line_key(unchanged), unchanged)

    def test_quoted_and_unquoted_lines_share_progress_and_unlinked_coverage(self):
        plain = '4"-PG-313050-750-FFLT-1H'
        quoted = '4"-PG-313050-"750"-FFLT-1H'
        docs = [{"id": 1, "drawing_number": "10113", "piping_line_number": plain},
                {"id": 2, "drawing_number": "10114", "piping_line_number": quoted},
                {"id": 3, "drawing_number": "10115", "piping_line_number": plain},
                {"id": 4, "drawing_number": "OTHER-SIZE", "piping_line_number": quoted.replace('4"-', '6"-')},
                {"id": 5, "drawing_number": "OTHER-SUFFIX", "piping_line_number": quoted.replace('-1H', '-2H')},
                {"id": 6, "drawing_number": "BRANCH", "piping_line_number": quoted + '/B1'}]
        packages = [{"document_id": 1, "discipline": "piping", "stages": {"welding": {"pct": 100}}},
                    {"document_id": 2, "discipline": "piping", "stages": {"welding": {"pct": 20}}}]
        payload = build_review(docs, packages)
        self.assertEqual(len(payload["lines"]), 4)
        line = next(line for line in payload["lines"] if line["key"] == plain)
        self.assertEqual(line["tag"], plain)
        self.assertEqual(line["drawing_ids"], ["1", "2", "3"])
        self.assertEqual(line["status"], "started")
        self.assertTrue(line["unlinked"])
        self.assertEqual([doc["lines"] for doc in payload["drawings"][:3]], [[plain], [quoted], [plain]])

    def test_all_drawings_aggregate_by_exact_line_and_nonpiping_progress_is_ignored(self):
        docs = [{"id": 1, "drawing_number": "A", "piping_line_number": '4"-DN-123-STD-H'},
                {"id": 2, "drawing_number": "B", "piping_line_number": '4"-DN-123-STD-H'},
                {"id": 3, "drawing_number": "C", "piping_line_number": '4"-DN-124-STD-H'}]
        packages = [{"document_id": 1, "discipline": "piping", "stages": {"welding": {"pct": 100}}},
                    {"document_id": 2, "discipline": "piping", "stages": {"welding": {"pct": 20}}},
                    {"document_id": 3, "discipline": "structural", "stages": {"welding": {"pct": 100}}}]
        payload = build_review(docs, packages)
        self.assertEqual(len(payload["drawings"]), 3)
        self.assertEqual([line["status"] for line in payload["lines"]], ["started", "unlinked"])
        self.assertEqual(payload["lines"][0]["drawing_ids"], ["1", "2"])

    def test_endpoint_requires_login_and_failure_is_not_reported_as_zero_progress(self):
        request = RequestFactory().get('/model-review/')
        request.user = SimpleNamespace(is_authenticated=False)
        self.assertEqual(model_review_view(request).status_code, 401)
        request.user.is_authenticated = True
        with patch('apps.core.model_review.review_payload', side_effect=RuntimeError('offline')), patch('logging.Logger.exception'):
            response = model_review_view(request)
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, '"available": false', status_code=503)

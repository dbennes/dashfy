from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory

from apps.core.model_review import aggregate_status, build_review, line_tags, package_state
from apps.core.views import model_review_view


class ModelReviewTests(SimpleTestCase):
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

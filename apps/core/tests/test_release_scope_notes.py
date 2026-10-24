"""Drawing selection never partitions shared project comments or minutes."""
from io import BytesIO
import re
from uuid import uuid4
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Client, User
from apps.core.models import SectionNote, SectionNoteEvent
from apps.core.release_scope import release_scope_context
from apps.core.section_notes import scope


class GlobalSectionNotesScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.planner = User.objects.create_user(username="notes-planner", role=User.Role.PLANNING)
        cls.viewer = User.objects.create_user(username="notes-viewer", role=User.Role.VIEWER)
        cls.records = {}
        for label, context in (
            ("legacy", {}), ("official", {"release_scope": "official"}),
            ("preparing", {"release_scope": "preparing"}), ("both", {"release_scope": "all"}),
        ):
            cls.records[label] = SectionNote.objects.create(
                author=cls.planner, author_name="Notes planner", section="s05", panel="model-review",
                note_date=timezone.localdate(), body=f"{label} project note", information_only=True, context=context,
            )

    def setUp(self):
        self.client.force_login(self.planner)
        self.url = reverse("core:section_notes")
        network = patch("psycopg2.connect", side_effect=AssertionError("No operational sources for notes tests"))
        network.start()
        self.addCleanup(network.stop)

    def data(self, **changes):
        return {
            "section": "s05", "panel": "model-review", "date": timezone.localdate().isoformat(),
            "body": "A new project note", "information_only": True, "request_id": str(uuid4()), **changes,
        }

    def create(self, selected, data):
        return self.client.post(self.url + f"?release_scope={selected}", data, content_type="application/json")

    def change(self, selected, note, status="resolved"):
        return self.client.post(
            reverse("core:section_note_status", args=[note.pk]) + f"?release_scope={selected}",
            {"status": status, "version": note.version}, content_type="application/json",
        )

    def test_all_drawing_selections_return_identical_comments_and_summary_for_same_tenant(self):
        expected = {note.pk for note in self.records.values()}
        for user in (self.viewer, self.planner):
            self.client.force_login(user)
            for selected in ("official", "preparing", "all"):
                with self.subTest(role=user.role, selected=selected):
                    response = self.client.get(self.url, {"panel": "model-review", "release_scope": selected})
                    self.assertEqual(response.status_code, 200)
                    notes = response.json()["notes"]
                    self.assertEqual({note["id"] for note in notes}, expected)
                    self.assertTrue(all("release_scope" not in note["context"] for note in notes))
                    summary = self.client.get(self.url, {"release_scope": selected}).json()["sections"]["model-review"]
                    self.assertEqual(summary["total"], 4)
                    self.assertEqual(summary["pending"], 0)
                    self.assertEqual(summary["people"], [{"id": self.planner.pk, "name": "Notes planner"}])

    def test_new_comments_ignore_drawing_selection_and_forged_context_metadata(self):
        for user in (self.viewer, self.planner):
            self.client.force_login(user)
            for selected in ("official", "preparing", "all"):
                with self.subTest(role=user.role, selected=selected):
                    response = self.create(selected, self.data(context={
                        "release_scope": selected, "discipline": "piping", "secret": "discard",
                    }))
                    self.assertEqual(response.status_code, 201)
                    returned = response.json()["note"]
                    self.assertEqual(returned["context"], {"discipline": "piping"})
                    self.assertEqual(SectionNote.objects.get(pk=returned["id"]).context, {"discipline": "piping"})
                    self.assertEqual(returned["author_id"], user.pk)
                    self.assertEqual(returned["events"][0]["actor"], str(user))

    def test_status_updates_are_global_and_preserve_authorship_history_and_old_metadata(self):
        note = self.records["preparing"]
        self.client.force_login(self.viewer)
        for selected, target in (("official", "resolved"), ("preparing", "pending"), ("all", "cancelled")):
            response = self.change(selected, note, target)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["note"]["events"][-1]["actor"], str(self.viewer))
            note.refresh_from_db()
        self.assertEqual(note.status, "cancelled")
        self.assertEqual(note.version, 4)
        self.assertEqual(note.author_id, self.planner.pk)
        self.assertEqual(note.body, "preparing project note")
        self.assertEqual(note.context, {"release_scope": "preparing"})
        self.assertEqual(note.events.count(), 3)
        self.assertEqual(self.change("official", self.records["both"]).status_code, 200)

    def test_minutes_export_is_the_same_across_drawings_scopes(self):
        expected = {note.body for note in self.records.values()}
        for user in (self.viewer, self.planner):
            self.client.force_login(user)
            for selected in ("official", "preparing", "all"):
                with self.subTest(role=user.role, selected=selected):
                    response = self.client.get(reverse("core:section_minutes"), {"release_scope": selected})
                    self.assertEqual(response.status_code, 200)
                    book = load_workbook(BytesIO(response.content), read_only=True)
                    try:
                        rows = list(book.active.iter_rows(min_row=6, values_only=True))
                        self.assertEqual({row[5] for row in rows}, expected)
                        self.assertEqual(book.active["A2"].value, "Comments across all panels · one row per comment · status history included")
                        self.assertTrue(all("release_scope" not in str(row[13] or "") for row in rows))
                    finally:
                        book.close()
        self.assertEqual(SectionNote.objects.count(), 4)

    def test_retries_across_drawing_selections_are_idempotent_but_keep_identity_guards(self):
        data = self.data()
        first = self.create("preparing", data)
        self.assertEqual(first.status_code, 201)
        note_id = first.json()["note"]["id"]
        for selected in ("official", "preparing", "all"):
            retry = self.create(selected, data)
            self.assertEqual(retry.status_code, 200)
            self.assertEqual(retry.json()["note"]["id"], note_id)
        self.assertEqual(SectionNoteEvent.objects.filter(note_id=note_id).count(), 1)
        self.assertEqual(self.create("all", {**data, "body": "Different content"}).status_code, 409)
        self.client.force_login(self.viewer)
        self.assertEqual(self.create("official", data).status_code, 409)

    def test_persisted_selection_metadata_is_ignored_without_rewriting_existing_notes(self):
        before = list(SectionNote.objects.order_by("pk").values())
        for label in ("legacy", "preparing", "both"):
            note = self.records[label]
            data = self.data(request_id=str(note.request_id), body=note.body)
            for selected in ("official", "preparing", "all"):
                retry = self.create(selected, data)
                self.assertEqual(retry.status_code, 200)
                self.assertNotIn("release_scope", retry.json()["note"]["context"])
        self.assertEqual(list(SectionNote.objects.order_by("pk").values()), before)

    def test_scope_helper_depends_on_project_and_tenant_not_drawing_context(self):
        expected = {note.pk for note in self.records.values()}
        for selected in ("official", "preparing", "all"):
            with release_scope_context(selected):
                self.assertEqual(set(scope(self.viewer).values_list("pk", flat=True)), expected)
                self.assertEqual(set(scope(self.planner).values_list("pk", flat=True)), expected)

    def test_tenant_isolation_remains_for_lists_status_summary_and_minutes(self):
        tenant = Client.objects.create(name="Isolated notes client", slug="isolated-notes")
        user = User.objects.create_user(username="tenant-supply-notes", role=User.Role.SUPPLY, client=tenant)
        self.client.force_login(user)
        for selected in ("official", "preparing", "all"):
            response = self.client.get(self.url, {"release_scope": selected, "panel": "model-review"})
            self.assertEqual(response.json()["total"], 0)
            summary = self.client.get(self.url, {"release_scope": selected}).json()["sections"]["model-review"]
            self.assertEqual(summary["total"], 0)
            self.assertEqual(self.change(selected, self.records["preparing"]).status_code, 404)
            response = self.client.get(reverse("core:section_minutes"), {"release_scope": selected})
            book = load_workbook(BytesIO(response.content), read_only=True)
            try:
                values = str(list(book.active.values))
                for note in self.records.values():
                    self.assertNotIn(note.body, values)
            finally:
                book.close()

    def test_modal_has_no_drawing_scope_label_or_scope_specific_api_urls(self):
        for selected in ("official", "preparing", "all"):
            response = self.client.get(reverse("core:home"), {"release_scope": selected})
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            dialog = re.search(r'<dialog id="sectionNotesDialog"[^>]*>', html).group()
            self.assertNotIn("release_scope", dialog)
            self.assertNotIn("data-release-scope", dialog)
            self.assertContains(response, '<span class="sn-eyebrow">PANEL FOLLOW-UP</span>')

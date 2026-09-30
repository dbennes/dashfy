import json

from django.test import SimpleTestCase

from apps.core.model_review import build_review, document_line_tags


class ModelReviewTieInTests(SimpleTestCase):
    drawing = "BNO-MABU-300-MP-2343-10197"
    stored = '10"-PL-043002-80-C-1-1'
    authored = 'TAM26-TP-05-10"-PL-043002-80-C-1-1/2H'

    def document(self, *, tag=None, candidate=None, middle="1\n1\nC", raw_text=None):
        return {
            "id": 286,
            "drawing_number": self.drawing,
            "discipline": "piping",
            "piping_line_number": self.stored if tag is None else tag,
            "raw_text": raw_text if raw_text is not None else
                f"PIPE SPOOLS\n{candidate or self.authored}\n{middle}\n{self.drawing}\nC02\nAO",
        }

    def test_real_title_block_patterns_restore_only_the_authored_line(self):
        cases = [
            ('16"-PM-038675-100-CC', 'TAM26-TP-01-16"-PM-038675-100-CC', "CC"),
            ('24"-PM-038674-100-CC', 'TAM26-TP-04-24"-PM-038674-100-CC', "CC"),
            (self.stored, self.authored, "C"),
            ('10"-PL-043005-80-C-1-1', 'TAM26-TP-06-10"-PL-043005-80-C-1-1/2H', "C"),
            ('4"-PG-313045-750-F1-1H', 'TAM26-TP-07-4"-PG-313045-"750"-F1-1H', "F1"),
            ('4"-PG-313048-750-F1-1H', 'TAM26-TP-08-4"-PG-313048-"750"-F1-1H', "F1"),
            ('3"-CC-423005-40S-SS', 'TAM26-TP25/26/56-3"-CC-423005-40S-SS', "SS"),
            ('2"-WI-403065-STD-AW', 'TAM26-TP-28A/28B-2"-WI-403065-STD-AW', "AW"),
            ('2"-BH-463389-80-A-P', 'TAM26-TP-49/50-2"-BH-463389-80-A-P', "A"),
            ('3/4"-CM-423050-281-J2', 'TAM26-TP-09-3/4"-CM-423050-"281"-J2', "J2"),
        ]
        for tag, candidate, pipe_class in cases:
            with self.subTest(tag=tag):
                doc = self.document(tag=tag, candidate=candidate, middle=f"1\n1\n{pipe_class}")
                self.assertEqual(document_line_tags(doc), [candidate])

    def test_continuation_references_do_not_replace_the_main_line(self):
        tag = '4"-PG-313045-750-F1-1H'
        candidate = 'TAM26-TP-07-4"-PG-313045-"750"-F1-1H'
        doc = self.document(tag=tag, raw_text=(
            f'{tag}\n1\n1\nF1\n{self.drawing}\nC02\n'
            f'CONT ON:\n{candidate}\nE 987341\nN 980070\nEL. 112148\nF5 G8 B9'
        ))
        self.assertEqual(document_line_tags(doc), [tag])

    def test_incomplete_or_invalid_title_blocks_keep_the_stored_tag(self):
        invalid = [
            f"{self.authored}\n1\n1\nC",
            f"{self.authored}\n1\n1\nC\nANOTHER-DRAWING",
            f"{self.authored}\n1\n1\nC\n\n{self.drawing}",
        ]
        for raw_text in invalid:
            with self.subTest(raw_text=raw_text):
                self.assertEqual(document_line_tags(self.document(raw_text=raw_text)), [self.stored])
        for middle in ["0\n1\nC", "2\n1\nC", "1\nX\nC", "1\n1\n123", "1\n1\nCONT ON:"]:
            with self.subTest(middle=middle):
                self.assertEqual(document_line_tags(self.document(middle=middle)), [self.stored])

    def test_no_number_only_match_or_missing_stored_tag_fallback(self):
        for tag in ['043002', '6"-PL-043002-80-C-1-1', '10"-PL-043002-160-C-1-1',
                    '10"-PL-043002-80-C-1', "", "N/A", self.stored + '; OTHER-LINE']:
            with self.subTest(tag=tag):
                doc = self.document(tag=tag)
                self.assertNotIn(self.authored, document_line_tags(doc))
        doc = self.document(candidate=self.authored.replace("TAM26-TP-05-", "TAM27-TP-05-"))
        self.assertEqual(document_line_tags(doc), [self.stored])

    def test_multiple_distinct_title_block_matches_remain_unmodified(self):
        doc = self.document()
        doc["raw_text"] += "\n" + self.document(candidate=self.authored.replace("TP-05-", "TP-06-"))["raw_text"]
        self.assertEqual(document_line_tags(doc), [self.stored])
        repeated = self.document()
        repeated["raw_text"] *= 2
        self.assertEqual(document_line_tags(repeated), [self.authored])

    def test_tie_in_and_main_line_keep_separate_progress_and_raw_text_stays_private(self):
        tag = '4"-PG-313045-750-F1-1H'
        candidate = 'TAM26-TP-07-4"-PG-313045-"750"-F1-1H'
        main = self.document(tag=tag, raw_text="SOURCE TEXT NOT FOR THE BROWSER")
        main["id"] = 87
        tie_in = self.document(tag=tag, candidate=candidate, middle="1\n1\nF1")
        tie_in["id"] = 288
        payload = build_review([main, tie_in], [
            {"document_id": 87, "discipline": "piping", "stages": {"welding": {"pct": 100}}},
            {"document_id": 288, "discipline": "piping", "stages": {"welding": {"pct": 0}}},
        ])
        self.assertEqual([drawing["lines"] for drawing in payload["drawings"]], [[tag], [candidate]])
        self.assertEqual(len(payload["lines"]), 2)
        by_tag = {line["tag"]: line for line in payload["lines"]}
        self.assertEqual(by_tag[tag]["status"], "completed")
        self.assertEqual(by_tag[tag]["drawing_ids"], ["87"])
        self.assertEqual(by_tag[candidate]["status"], "not_started")
        self.assertEqual(by_tag[candidate]["drawing_ids"], ["288"])
        self.assertNotIn("raw_text", json.dumps(payload))
        self.assertNotIn("SOURCE TEXT NOT FOR THE BROWSER", json.dumps(payload))

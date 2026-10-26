"""Execute the read-only manifest queries against disposable logistics fixtures."""
import sqlite3
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.tracking_source import map_containers, map_containers_safe, shipment_items


class DatafyContainersTests(SimpleTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            create table core_project (id integer, created_at text);
            insert into core_project values (1, '2026-01-01'), (2, '2026-02-01');
            create table logistics_container
                (id integer, project_id integer, number text, owner text);
            create table logistics_shipment
                (id integer, project_id integer, container_id integer, number text,
                 status text, origin text, destination text, sent_at timestamp,
                 created_at timestamp, container_number_snapshot text);
            create table logistics_shipmentitem
                (id integer, shipment_id integer, removed_at timestamp,
                 material_code_snapshot text, rfid_snapshot text,
                 description_snapshot text, quantity_snapshot real,
                 received_quantity real, unit_snapshot text, check_status text,
                 check_notes text, drawing_number_snapshot text, log_code_snapshot text);
        """)
        for pk, number, status, project in [
            (13, "HH23-033", "sent", 1), (14, "334031", "sent", 1),
            (15, "NRSM 052", "sent", 1), (16, "RRR-2000120", "sent", 1),
            (17, "LOADING", "draft", 1), (18, "ARRIVED", "delivered", 1),
            (19, "DONE", "verified", 1), (20, "ISSUES", "discrepancy", 1),
            (21, "CANCELLED", "cancelled", 1), (22, "OTHER PROJECT", "sent", 2),
        ]:
            self.db.execute("insert into logistics_container values (?, ?, ?, ?)",
                            (pk, project, number, "UTC"))
            self.db.execute("insert into logistics_shipment values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (pk, project, pk, f"SHP-2026-{pk:04d}", status,
                             "Mabu Warehouse", "Bonga North", None, None, number))
        for pk, status, qty, received, removed in [
            (1, "pending", 2.5, None, None), (2, "ok", 3, 3, None),
            (3, "damaged", 4, 1, None), (4, "missing", 5, 0, "2026-10-20"),
        ]:
            self.db.execute("insert into logistics_shipmentitem values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (pk, 16, removed, f"MAT-{pk}", "RFID", "Manifest description",
                             qty, received, "EA", status, "Check note", "DRAWING", "LOG"))
        self.db.commit()
        source = patch("apps.core.real_sources._datafy_conn")
        self.source = source.start()
        self.source.return_value.__enter__.return_value = self.db
        self.addCleanup(source.stop)
        legacy = patch("apps.core.real_sources._taskfy_conn",
                       side_effect=AssertionError("Vessel cargo must not read legacy Trackfy"))
        legacy.start()
        self.addCleanup(legacy.stop)

    def test_only_in_transit_default_project_containers_are_returned(self):
        payload = map_containers()
        self.assertEqual({c["number"] for c in payload["containers"]},
                         {"HH23-033", "334031", "NRSM 052", "RRR-2000120"})
        self.assertEqual(payload["totals"],
                         {"fleet": 9, "containers": 4, "with_open": 4, "open_shipments": 4})
        container = next(c for c in payload["containers"] if c["id"] == 16)
        self.assertEqual(container["status"], "In transit")
        shipment = container["open_shipments"][0]
        self.assertEqual(shipment["report"], "SHP-2026-0016")
        self.assertEqual(shipment["items"], 3)
        self.assertEqual(shipment["issues"], 1)
        self.assertEqual(shipment["origin"], "Mabu Warehouse")

    def test_receiving_a_container_removes_it_from_the_next_read(self):
        self.db.execute("update logistics_shipment set status = 'delivered' where id = 16")
        self.assertNotIn(16, [c["id"] for c in map_containers()["containers"]])

    def test_manifest_identity_survives_container_rename(self):
        self.db.execute("update logistics_container set number = 'RENAMED' where id = 16")
        container = next(c for c in map_containers()["containers"] if c["id"] == 16)
        self.assertEqual(container["number"], "RRR-2000120")
        self.assertEqual(shipment_items(16)["shipment"]["container"], "RRR-2000120")

    def test_contents_use_manifest_snapshots_and_exclude_removed_items(self):
        payload = shipment_items(16)
        self.assertTrue(payload["found"])
        self.assertEqual(payload["shipment"]["report"], "SHP-2026-0016")
        self.assertEqual(payload["total_count"], 3)
        self.assertEqual(payload["returned_count"], 3)
        self.assertEqual(payload["counts"], {"pending": 1, "ok": 1, "missing": 0, "damaged": 1})
        self.assertEqual(payload["checked"], 2)
        self.assertEqual(payload["items"][0]["quantity"], 2.5)
        self.assertIsNone(payload["items"][0]["received_quantity"])
        self.assertEqual(payload["items"][0]["code"], "MAT-1")
        self.assertEqual(payload["items"][0]["description"], "Manifest description")

    def test_contents_remain_bounded(self):
        payload = shipment_items(16, limit=1)
        self.assertEqual(payload["total_count"], 3)
        self.assertEqual(payload["returned_count"], 1)

    def test_missing_or_other_project_shipment_is_not_returned(self):
        for pk in (999, 22):
            with self.subTest(pk=pk):
                payload = shipment_items(pk)
                self.assertFalse(payload["found"])
                self.assertEqual(payload["items"], [])

    def test_empty_source_does_not_create_a_default_project(self):
        self.db.execute("delete from core_project")
        self.assertEqual(map_containers()["containers"], [])
        self.assertEqual(self.db.execute("select count(*) from core_project").fetchone()[0], 0)

    def test_source_queries_are_read_only(self):
        queries = []
        self.db.set_trace_callback(queries.append)
        map_containers()
        shipment_items(16)
        self.assertTrue(queries)
        self.assertTrue(all(q.lstrip().lower().startswith("select") for q in queries))

    def test_source_failure_does_not_fall_back_to_trackfy(self):
        self.source.side_effect = RuntimeError("DATAFY unavailable")
        payload = map_containers_safe()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["containers"], [])

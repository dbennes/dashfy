from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase, override_settings

from apps.vessels.admin import VesselAdmin, VesselPositionAdmin
from apps.vessels.ais import ingest_ais_message, parse_ais_message
from apps.vessels.models import Vessel, VesselPosition


MMSI = "123456789"
START = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
RECEIVED = START + timedelta(days=1)


def position_frame(seconds=0, message_type="PositionReport", **fields):
    body = {
        "Valid": True, "UserID": int(MMSI), "Latitude": 4.18291, "Longitude": 6.81921,
        "Sog": 11.3, "Cog": 223.0, "TrueHeading": 224, "NavigationalStatus": 0, "Timestamp": 59,
    }
    body.update(fields)
    return {
        "MessageType": message_type,
        "MetaData": {"MMSI": int(MMSI), "time_utc": (START + timedelta(seconds=seconds)).isoformat(),
                     "Latitude": 80, "Longitude": 90, "ShipName": "AIS NAME@@@@"},
        "Message": {message_type: body},
    }


def static_frame(seconds=0, message_type="ShipStaticData", **fields):
    result = position_frame(seconds, message_type)
    result["Message"][message_type] = {"Valid": True, "UserID": int(MMSI), **fields}
    return result


class AISParserTests(SimpleTestCase):
    def test_class_a_and_b_positions_use_body_coordinates_and_full_metadata_timestamp(self):
        for message_type in ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"):
            with self.subTest(message_type=message_type):
                raw = position_frame(message_type=message_type)
                raw["MetaData"]["time_utc"] = "2026-09-15 12:00:00.123456789 +0000 UTC"
                result = parse_ais_message(json.dumps(raw).encode("utf-8"), now=RECEIVED)
                self.assertEqual(result.mmsi, MMSI)
                self.assertEqual(result.timestamp, START.replace(microsecond=123456))
                self.assertEqual(result.position["latitude"], 4.18291)
                self.assertEqual(result.position["longitude"], 6.81921)
                self.assertEqual(result.position["sog"], 11.3)

    def test_ais_second_only_or_missing_full_timestamp_never_becomes_a_position(self):
        for timestamp in (None, 59, "59", "2026-09-15T12:00:00", "not a timestamp"):
            raw = position_frame()
            raw["MetaData"]["time_utc"] = timestamp
            self.assertIsNone(parse_ais_message(raw, now=RECEIVED))
        raw = position_frame()
        raw["MetaData"]["time_utc"] = "2026-09-15T13:00:00+01:00"
        self.assertEqual(parse_ais_message(raw, now=RECEIVED).timestamp, START)

    def test_invalid_frames_identifiers_future_times_and_position_sentinels_are_ignored(self):
        cases = [b"\xff", "not JSON", "[]", {}, {"MessageType": "SubscriptionConfirmation"},
                 {"MessageType": []}, {"MessageType": {"invalid": "type"}}]
        for fields in ({"Valid": False}, {"UserID": 987654321}, {"Latitude": 91}, {"Longitude": 181},
                       {"Latitude": float("nan")}, {"Longitude": float("inf")}, {"Latitude": "4.2"},
                       {"Longitude": None}, {"Latitude": True}, {"Latitude": 10 ** 400}):
            cases.append(position_frame(**fields))
        for mmsi in ("12345678", "1234567890", "１２３４５６７８９", True):
            raw = position_frame()
            raw["MetaData"]["MMSI"] = mmsi
            cases.append(raw)
        future = position_frame()
        future["MetaData"]["time_utc"] = (RECEIVED + timedelta(minutes=6)).isoformat()
        cases.append(future)
        overflow = position_frame()
        overflow["MetaData"]["time_utc"] = "0001-01-01T00:00:00+23:00"
        cases.append(overflow)
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                self.assertIsNone(parse_ais_message(raw, now=RECEIVED))

    def test_unavailable_navigation_values_are_null_and_zero_coordinates_are_valid(self):
        result = parse_ais_message(position_frame(Latitude=0, Longitude=0, Sog=102.3, Cog=360,
                                                  TrueHeading=511, NavigationalStatus=15), now=RECEIVED)
        self.assertEqual(result.position, {"latitude": 0, "longitude": 0, "sog": None, "cog": None,
                                           "heading": None, "navigational_status": None})
        result = parse_ais_message(position_frame(Sog=0, Cog=0, TrueHeading=0, NavigationalStatus=0), now=RECEIVED)
        self.assertEqual(result.position["sog"], 0)
        self.assertEqual(result.position["heading"], 0)

    def test_ship_static_voyage_fields_and_eta_preserve_declared_values_without_inferred_year(self):
        raw = static_frame(Name="VESSEL NAME@@@@", ImoNumber=1234567, Type=70,
                           Destination="BONNY@@@@", MaximumStaticDraught=8.5,
                           Eta={"Month": 9, "Day": 16, "Hour": 18, "Minute": 0})
        before = deepcopy(raw)
        result = parse_ais_message(raw, now=RECEIVED)
        self.assertIsNone(result.position)
        self.assertEqual(result.static_fields, {"name": "VESSEL NAME", "imo": "1234567", "vessel_type": "70",
                                               "destination": "BONNY", "draught": 8.5,
                                               "eta": {"month": 9, "day": 16, "hour": 18, "minute": 0}})
        self.assertNotIn("year", result.static_fields["eta"])
        self.assertEqual(raw, before)

    def test_unknown_eta_and_draught_do_not_create_dates_or_zero_depth(self):
        raw = static_frame(Destination="", MaximumStaticDraught=0,
                           Eta={"Month": 0, "Day": 0, "Hour": 24, "Minute": 60})
        result = parse_ais_message(raw, now=RECEIVED)
        self.assertEqual(result.static_fields, {"destination": "", "eta": {}, "draught": None})
        raw["Message"]["ShipStaticData"]["Eta"] = {"Month": 2, "Day": 31, "Hour": 18, "Minute": 60}
        result = parse_ais_message(raw, now=RECEIVED)
        self.assertEqual(result.static_fields["eta"], {"month": 2, "day": None, "hour": 18, "minute": None})

    def test_class_b_static_parts_use_only_the_valid_selected_part(self):
        report_a = static_frame(message_type="StaticDataReport", PartNumber=False,
                                ReportA={"Valid": True, "Name": "CLASS B@@@@"},
                                ReportB={"Valid": False, "ShipType": 0})
        self.assertEqual(parse_ais_message(report_a, now=RECEIVED).static_fields, {"name": "CLASS B"})
        report_b = static_frame(message_type="StaticDataReport", PartNumber=True,
                                ReportA={"Valid": False, "Name": "STALE"},
                                ReportB={"Valid": True, "ShipType": 60})
        self.assertEqual(parse_ais_message(report_b, now=RECEIVED).static_fields, {"vessel_type": "60"})
        report_b["Message"]["StaticDataReport"]["ReportB"]["Valid"] = False
        self.assertIsNone(parse_ais_message(report_b, now=RECEIVED))


@override_settings(AIS_POSITION_INTERVAL_SECONDS=180, AIS_POSITION_MIN_SECONDS=10,
                   AIS_POSITION_DISTANCE_METERS=250, AIS_POSITION_COURSE_DEGREES=15)
class AISPersistenceTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi=MMSI, name="Registered vessel")

    def ingest(self, seconds=0, **fields):
        return ingest_ais_message(position_frame(seconds, **fields), now=RECEIVED)

    def test_stationary_vessel_refreshes_latest_every_message_but_history_at_interval(self):
        self.assertTrue(self.ingest().position_persisted)
        self.assertFalse(self.ingest(60).position_persisted)
        self.assertFalse(self.ingest(179).position_persisted)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_seen, START + timedelta(seconds=179))
        self.assertEqual(self.vessel.positions.count(), 1)
        self.assertTrue(self.ingest(180).position_persisted)
        self.assertEqual(list(self.vessel.positions.values_list("timestamp", flat=True)), [START, START + timedelta(seconds=180)])

    def test_relevant_movement_is_saved_after_cooldown_using_last_persisted_position(self):
        self.ingest()
        self.assertFalse(self.ingest(5, Latitude=4.2).position_persisted)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_latitude, 4.2)
        self.assertTrue(self.ingest(10, Latitude=4.2).position_persisted)
        self.assertEqual(self.vessel.positions.count(), 2)

    def test_course_change_uses_circular_angle_and_minimum_cooldown(self):
        self.ingest(Cog=359)
        self.assertFalse(self.ingest(5, Cog=180).position_persisted)
        self.assertFalse(self.ingest(15, Cog=1).position_persisted)
        self.assertTrue(self.ingest(30, Cog=14).position_persisted)
        self.assertEqual(self.vessel.positions.count(), 2)

    def test_duplicate_and_out_of_order_positions_never_regress_current_or_rewrite_history(self):
        self.ingest()
        self.ingest(200, Latitude=4.3)
        before = list(self.vessel.positions.values())
        self.assertFalse(self.ingest(200, Latitude=20).accepted)
        self.assertFalse(self.ingest(100, Latitude=30).accepted)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_seen, START + timedelta(seconds=200))
        self.assertEqual(self.vessel.last_latitude, 4.3)
        self.assertEqual(list(self.vessel.positions.values()), before)

    def test_static_message_metadata_never_moves_the_vessel_and_old_voyage_data_is_ignored(self):
        self.ingest(100)
        raw = static_frame(120, Destination="BONNY", Eta={"Month": 9, "Day": 16, "Hour": 18, "Minute": 0})
        self.assertTrue(ingest_ais_message(raw, now=RECEIVED).static_updated)
        stale = static_frame(110, Destination="STALE DESTINATION")
        self.assertFalse(ingest_ais_message(stale, now=RECEIVED).accepted)
        newest = static_frame(300, MaximumStaticDraught=8.5)
        self.assertTrue(ingest_ais_message(newest, now=RECEIVED).static_updated)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_seen, START + timedelta(seconds=100))
        self.assertEqual(self.vessel.last_latitude, 4.18291)
        self.assertEqual(self.vessel.destination, "BONNY")
        self.assertEqual(self.vessel.last_static_seen, START + timedelta(seconds=300))
        self.assertEqual(self.vessel.positions.count(), 1)

    def test_extended_class_b_updates_name_type_and_position_together(self):
        raw = position_frame(message_type="ExtendedClassBPositionReport", Name="NEW AIS NAME@@", Type=60)
        result = ingest_ais_message(raw, now=RECEIVED)
        self.assertTrue(result.position_updated)
        self.assertTrue(result.static_updated)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.name, "NEW AIS NAME")
        self.assertEqual(self.vessel.vessel_type, "60")

    def test_class_b_static_parts_at_same_timestamp_combine_without_clearing_fields(self):
        report_a = static_frame(100, message_type="StaticDataReport", PartNumber=False,
                                ReportA={"Valid": True, "Name": "CLASS B"})
        report_b = static_frame(100, message_type="StaticDataReport", PartNumber=True,
                                ReportB={"Valid": True, "ShipType": 70})
        ingest_ais_message(report_a, now=RECEIVED)
        ingest_ais_message(report_b, now=RECEIVED)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.name, "CLASS B")
        self.assertEqual(self.vessel.vessel_type, "70")
        self.assertIsNone(self.vessel.last_seen)
        self.assertEqual(self.vessel.positions.count(), 0)

    def test_inactive_and_unregistered_vessels_are_not_collected_or_created(self):
        self.ingest()
        self.vessel.is_active = False
        self.vessel.save(update_fields=["is_active"])
        self.assertFalse(self.ingest(200).accepted)
        unknown = position_frame(300, UserID=987654321)
        unknown["MetaData"]["MMSI"] = 987654321
        self.assertFalse(ingest_ais_message(unknown, now=RECEIVED).accepted)
        self.assertEqual(Vessel.objects.count(), 1)
        self.assertEqual(self.vessel.positions.count(), 1)
        with self.assertRaises(ProtectedError):
            self.vessel.delete()

    def test_history_rejects_duplicate_timestamps_and_non_ais_sources(self):
        self.ingest()
        for fields in ({"source": "AIS", "timestamp": START},
                       {"source": "PREDICT", "timestamp": START + timedelta(seconds=1)}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                VesselPosition.objects.create(vessel=self.vessel, latitude=4, longitude=6, **fields)
        self.assertEqual(self.vessel.positions.count(), 1)

    def test_registration_validation_and_admin_preserve_existing_history(self):
        for mmsi in ("12345678", "１２３４５６７８９", "abcdefghi"):
            with self.assertRaises(ValidationError):
                Vessel(mmsi=mmsi).full_clean()
        self.vessel.mmsi = "987654321"
        with self.assertRaises(ValidationError):
            self.vessel.full_clean()
        site = AdminSite()
        self.assertFalse(VesselAdmin(Vessel, site).has_delete_permission(None))
        history_admin = VesselPositionAdmin(VesselPosition, site)
        self.assertFalse(history_admin.has_add_permission(None))
        self.assertFalse(history_admin.has_change_permission(None))
        self.assertFalse(history_admin.has_delete_permission(None))

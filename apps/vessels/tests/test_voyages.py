from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from apps.vessels.ais import ingest_ais_message
from apps.vessels.imports import import_report
from apps.vessels.models import Vessel
from apps.vessels.serializers import vessel_data
from apps.vessels.voyages import accept_destination_change, advance_voyage, configured_geofences, voyage_payload

from .test_ais import position_frame, static_frame, START as AIS_START, RECEIVED


PORT = {"id": "aveon-jetty-ph", "name": "AVEON JETTY PH", "latitude": 4.7942467,
        "longitude": 6.9417582, "radius_m": 3000}
OTHER_PORT = {"id": "other-port", "name": "OTHER PORT", "latitude": 4.0,
              "longitude": 6.0, "radius_m": 2000}
BONGA = {"id": "bonga-north", "name": "BONGA NORTH", "latitude": 4.5575266,
         "longitude": 4.6164432, "radius_m": 3000}
SHUTTLE_MMSI = "636023616"
SHUTTLE_ROUTES = {SHUTTLE_MMSI: [PORT["id"], BONGA["id"]]}
START = datetime(2026, 9, 16, 14, 57, 3, tzinfo=timezone.utc)


def advance(state=None, *, when=START, latitude=PORT["latitude"], longitude=PORT["longitude"],
            geofences=None):
    return advance_voyage(state or {}, latitude=latitude, longitude=longitude, timestamp=when,
                          geofences=[PORT] if geofences is None else geofences)


def current_vessel(*, state=None, latitude=PORT["latitude"], longitude=PORT["longitude"],
                   when=START, destination=PORT["name"]):
    return SimpleNamespace(voyage_state=state or {}, last_latitude=latitude,
                           last_longitude=longitude, last_seen=when, destination=destination)


@override_settings(AIS_PORT_GEOFENCES=[PORT])
class VoyageTransitionTests(SimpleTestCase):
    def test_existing_vessel_inside_radius_is_arrived_without_mutation(self):
        vessel = current_vessel()
        before = deepcopy(vars(vessel))
        payload = voyage_payload(vessel)
        self.assertEqual(payload["status"], "arrived")
        self.assertEqual(payload["current_port"], PORT)
        self.assertEqual(payload["destination"], PORT)
        self.assertEqual(payload["arrived_at"], START.isoformat())
        self.assertIsNone(payload["origin"])
        self.assertEqual(vars(vessel), before)

    def test_movement_within_fixed_circle_preserves_arrival_time(self):
        arrived = advance()
        moved = advance(arrived, when=START + timedelta(minutes=10), latitude=PORT["latitude"] + 0.01)
        self.assertEqual(moved["status"], "arrived")
        self.assertEqual(moved["arrived_at"], arrived["arrived_at"])
        self.assertIsNone(moved["departed_at"])
        self.assertEqual(moved["current_port"]["latitude"], PORT["latitude"])

    def test_radius_classifies_inside_and_outside_without_following_vessel(self):
        self.assertEqual(advance(latitude=PORT["latitude"] + 0.026)["status"], "arrived")
        self.assertEqual(advance(latitude=PORT["latitude"] + 0.028)["status"], "underway")

    def test_departure_sets_stable_origin_and_suppresses_old_destination(self):
        departed_at = START + timedelta(hours=2)
        departed = advance(advance(), when=departed_at, latitude=5.0)
        vessel = current_vessel(state=departed, latitude=5.0, when=departed_at,
                                destination=" AVEON  JETTY PH ")
        payload = voyage_payload(vessel)
        self.assertEqual(payload["status"], "underway")
        self.assertEqual(payload["origin"], PORT)
        self.assertEqual(payload["departed_at"], departed_at.isoformat())
        self.assertIsNone(payload["current_port"])
        self.assertIsNone(payload["destination"])
        self.assertEqual(vessel.destination, " AVEON  JETTY PH ")
        later = advance(departed, when=departed_at + timedelta(days=1), latitude=6.0)
        self.assertEqual(later["origin"], PORT)
        self.assertEqual(later["departed_at"], departed["departed_at"])

    def test_new_declared_destination_is_used_without_changing_observed_state(self):
        departed_at = START + timedelta(hours=2)
        departed = advance(advance(), when=departed_at, latitude=5.0)
        vessel = current_vessel(state=departed, latitude=5.0, when=departed_at, destination="BONGA")
        before = deepcopy(departed)
        self.assertEqual(voyage_payload(vessel)["destination"], {"name": "BONGA"})
        vessel.destination = OTHER_PORT["name"]
        self.assertEqual(voyage_payload(vessel, geofences=[PORT, OTHER_PORT])["destination"], OTHER_PORT)
        self.assertEqual(departed, before)

    def test_return_updates_arrival_after_departure(self):
        departed = advance(advance(), when=START + timedelta(hours=1), latitude=5.0)
        returned_at = START + timedelta(hours=3)
        returned = advance(departed, when=returned_at)
        self.assertEqual(returned["status"], "arrived")
        self.assertEqual(returned["origin"], PORT)
        self.assertEqual(returned["current_port"], PORT)
        self.assertEqual(returned["arrived_at"], returned_at.isoformat())

    def test_next_port_arrival_preserves_previous_port_as_origin(self):
        arrived = advance()
        second = advance(arrived, when=START + timedelta(hours=12),
                         latitude=OTHER_PORT["latitude"], longitude=OTHER_PORT["longitude"],
                         geofences=[PORT, OTHER_PORT])
        self.assertEqual(second["origin"], PORT)
        self.assertEqual(second["current_port"], OTHER_PORT)
        self.assertEqual(second["status"], "arrived")

    def test_old_equal_and_invalid_positions_cannot_rewind_trip(self):
        state = advance(advance(), when=START + timedelta(hours=1), latitude=5.0)
        for when in (START, START + timedelta(hours=1), "invalid", None, START.replace(tzinfo=None)):
            with self.subTest(when=when):
                self.assertEqual(advance(state, when=when), state)
        for latitude in (None, True, "4.7", 91, float("nan"), float("inf")):
            with self.subTest(latitude=latitude):
                self.assertEqual(advance(state, when=START + timedelta(days=1), latitude=latitude), state)

    def test_missing_position_does_not_claim_arrival_from_destination_text(self):
        payload = voyage_payload(current_vessel(latitude=None, longitude=None, when=None))
        self.assertEqual(payload["status"], "unknown")
        self.assertIsNone(payload["current_port"])
        self.assertIsNone(payload["position_timestamp"])
        self.assertEqual(payload["destination"], PORT)
        self.assertEqual(payload["geofences"], [PORT])

    def test_invalid_geofences_are_ignored_and_zero_coordinates_are_valid(self):
        invalid = [{**PORT, "latitude": True}, {**PORT, "radius_m": 0}, {**PORT, "longitude": 181},
                   {**PORT, "name": ""}, None]
        self.assertEqual(configured_geofences(invalid), [])
        origin_port = {**PORT, "latitude": 0, "longitude": 0}
        self.assertEqual(advance(latitude=0, longitude=0, geofences=[origin_port])["status"], "arrived")

    def test_destination_change_dated_before_departure_cannot_clear_suppression(self):
        departed = advance(advance(), when=START + timedelta(hours=1), latitude=5.0)
        changed = accept_destination_change(departed, previous_destination="BONGA", destination=PORT["name"],
                                            timestamp=START + timedelta(minutes=30))
        self.assertEqual(changed, departed)

    def test_new_departure_resets_suppression_after_a_completed_return(self):
        departed = advance(advance(), when=START + timedelta(hours=1), latitude=5.0)
        changed = accept_destination_change(departed, previous_destination="BONGA", destination=PORT["name"],
                                            timestamp=START + timedelta(hours=2))
        self.assertIsNone(changed["suppressed_destination"])
        returned = advance(changed, when=START + timedelta(hours=3))
        departed_again = advance(returned, when=START + timedelta(hours=4), latitude=5.0)
        self.assertEqual(departed_again["suppressed_destination"], PORT["name"])
        vessel = current_vessel(state=departed_again, latitude=5.0, when=START + timedelta(hours=4))
        payload = voyage_payload(vessel)
        self.assertIsNone(payload["destination"])
        self.assertNotIn("suppressed_destination", payload)


@override_settings(AIS_PORT_GEOFENCES=[PORT])
class VoyagePersistenceTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi="123456789", name="Registered vessel",
                                            destination=PORT["name"], last_latitude=PORT["latitude"],
                                            last_longitude=PORT["longitude"], last_seen=START)

    def report(self, *, when=START, latitude=PORT["latitude"], destination=PORT["name"]):
        return ("MMSI,LAT,LON,TIMESTAMP,DESTINATION\n"
                f"{self.vessel.mmsi},{latitude},{PORT['longitude']},{when.isoformat()},{destination}\n")

    def test_current_payload_derives_arrival_without_database_writes_or_queries(self):
        with self.assertNumQueries(0):
            payload = vessel_data(self.vessel, now=START + timedelta(days=2))
        self.assertEqual(payload["voyage"]["status"], "arrived")
        self.assertEqual(payload["status"], "NO_RECENT_AIS")
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.voyage_state, {})

    def test_next_import_detects_departure_from_existing_unpersisted_arrival(self):
        moment = START + timedelta(hours=1)
        result = import_report(self.report(when=moment, latitude=5.0), now=moment)
        self.vessel.refresh_from_db()
        self.assertEqual(result.vessels_advanced, 1)
        self.assertEqual(self.vessel.voyage_state["status"], "underway")
        self.assertEqual(self.vessel.voyage_state["origin"], PORT)
        self.assertEqual(self.vessel.voyage_state["arrived_at"], START.isoformat())
        self.assertEqual(self.vessel.voyage_state["departed_at"], moment.isoformat())
        self.assertIsNone(vessel_data(self.vessel)["voyage"]["destination"])
        self.assertEqual(self.vessel.destination, PORT["name"])

    def test_new_import_destination_replaces_displayed_target_without_moving_origin(self):
        moment = START + timedelta(hours=1)
        import_report(self.report(when=moment, latitude=5.0, destination="BONGA"), now=moment)
        self.vessel.refresh_from_db()
        payload = vessel_data(self.vessel)["voyage"]
        self.assertEqual(payload["origin"], PORT)
        self.assertEqual(payload["destination"], {"name": "BONGA"})

    def test_old_and_duplicate_imports_never_reset_departure_or_target(self):
        moment = START + timedelta(hours=1)
        import_report(self.report(when=moment, latitude=5.0, destination="BONGA"), now=moment)
        self.vessel.refresh_from_db()
        before = deepcopy(self.vessel.voyage_state)
        for when in (START, moment):
            import_report(self.report(when=when), now=moment)
            self.vessel.refresh_from_db()
            self.assertEqual(self.vessel.voyage_state, before)
            self.assertEqual(self.vessel.destination, "BONGA")
            self.assertEqual(self.vessel.last_latitude, 5.0)

    def test_dry_run_cannot_advance_voyage(self):
        moment = START + timedelta(hours=1)
        import_report(self.report(when=moment, latitude=5.0), now=moment, dry_run=True)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.voyage_state, {})
        self.assertEqual(self.vessel.last_seen, START)

    def test_importing_return_marks_arrived_again(self):
        departure = START + timedelta(hours=1)
        arrival = START + timedelta(hours=3)
        import_report(self.report(when=departure, latitude=5.0), now=arrival)
        import_report(self.report(when=arrival), now=arrival)
        self.vessel.refresh_from_db()
        payload = vessel_data(self.vessel)["voyage"]
        self.assertEqual(payload["status"], "arrived")
        self.assertEqual(payload["destination"], PORT)
        self.assertEqual(payload["arrived_at"], arrival.isoformat())

    def test_live_ais_uses_same_departure_rules_and_ignores_old_positions(self):
        self.vessel.last_seen = AIS_START
        self.vessel.save(update_fields=["last_seen"])
        ingest_ais_message(position_frame(60, Latitude=5.0, Longitude=PORT["longitude"]), now=RECEIVED)
        self.vessel.refresh_from_db()
        before = deepcopy(self.vessel.voyage_state)
        self.assertEqual(before["status"], "underway")
        self.assertEqual(before["origin"], PORT)
        ingest_ais_message(position_frame(30, Latitude=PORT["latitude"], Longitude=PORT["longitude"]), now=RECEIVED)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.voyage_state, before)

    def test_static_ais_updates_destination_without_inventing_movement(self):
        self.vessel.last_seen = AIS_START
        self.vessel.save(update_fields=["last_seen"])
        ingest_ais_message(position_frame(60, Latitude=5.0, Longitude=PORT["longitude"]), now=RECEIVED)
        self.vessel.refresh_from_db()
        before = deepcopy(self.vessel.voyage_state)
        ingest_ais_message(static_frame(120, Destination="BONGA"), now=RECEIVED)
        self.vessel.refresh_from_db()
        before["suppressed_destination"] = None
        self.assertEqual(self.vessel.voyage_state, before)
        self.assertEqual(vessel_data(self.vessel)["voyage"]["destination"], {"name": "BONGA"})

    def static(self, when, **fields):
        message = static_frame(**fields)
        message["MetaData"]["time_utc"] = when.isoformat()
        return ingest_ais_message(message, now=START + timedelta(days=1))

    def test_older_static_ais_cannot_replace_new_import_destination_but_updates_other_fields(self):
        imported_at = START + timedelta(hours=1)
        import_report(self.report(when=imported_at, latitude=5.0, destination="BONGA"), now=imported_at)
        older_static_at = START + timedelta(minutes=30)
        self.static(older_static_at, Destination="OUTDATED", Name="NEW VESSEL NAME", MaximumStaticDraught=8.5)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.destination, "BONGA")
        self.assertEqual(self.vessel.destination_seen_at, imported_at)
        self.assertEqual(self.vessel.name, "NEW VESSEL NAME")
        self.assertEqual(self.vessel.draught, 8.5)
        self.assertEqual(self.vessel.last_static_seen, older_static_at)
        self.assertEqual(vessel_data(self.vessel)["voyage"]["destination"], {"name": "BONGA"})

    def test_new_position_import_cannot_replace_a_newer_static_destination(self):
        declared_at = START + timedelta(hours=2)
        self.static(declared_at, Destination="ONNE")
        imported_at = START + timedelta(hours=1)
        import_report(self.report(when=imported_at, latitude=5.0, destination="BONGA"), now=declared_at)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_seen, imported_at)
        self.assertEqual(self.vessel.last_latitude, 5.0)
        self.assertEqual(self.vessel.destination, "ONNE")
        self.assertEqual(self.vessel.destination_seen_at, declared_at)

    def test_destination_clock_is_independent_of_newer_unrelated_static_metadata(self):
        imported_at = START + timedelta(hours=1)
        import_report(self.report(when=imported_at, latitude=5.0, destination="BONGA"), now=imported_at)
        name_at = START + timedelta(hours=3)
        self.static(name_at, Name="LATEST NAME")
        destination_at = START + timedelta(hours=2)
        result = self.static(destination_at, Destination="ONNE", Name="OLDER NAME")
        self.vessel.refresh_from_db()
        self.assertTrue(result.static_updated)
        self.assertEqual(self.vessel.destination, "ONNE")
        self.assertEqual(self.vessel.destination_seen_at, destination_at)
        self.assertEqual(self.vessel.name, "LATEST NAME")
        self.assertEqual(self.vessel.last_static_seen, name_at)

    def test_equal_timestamp_destination_keeps_the_existing_declaration(self):
        moment = START + timedelta(hours=1)
        import_report(self.report(when=moment, latitude=5.0, destination="BONGA"), now=moment)
        self.static(moment, Destination="DIFFERENT")
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.destination, "BONGA")
        self.assertEqual(self.vessel.destination_seen_at, moment)

    def test_existing_legacy_destination_is_protected_before_first_new_declaration(self):
        self.static(START - timedelta(hours=1), Destination="OUTDATED", Name="STATIC NAME")
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.destination, PORT["name"])
        self.assertIsNone(self.vessel.destination_seen_at)
        self.assertEqual(self.vessel.name, "STATIC NAME")
        declared_at = START + timedelta(hours=1)
        self.static(declared_at, Destination="BONGA")
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.destination, "BONGA")
        self.assertEqual(self.vessel.destination_seen_at, declared_at)

    def test_newer_empty_static_declaration_cannot_be_refilled_by_older_import(self):
        declared_at = START + timedelta(hours=2)
        self.static(declared_at, Destination="")
        imported_at = START + timedelta(hours=1)
        import_report(self.report(when=imported_at, latitude=5.0, destination="BONGA"), now=declared_at)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.destination, "")
        self.assertEqual(self.vessel.destination_seen_at, declared_at)
        self.assertIsNone(vessel_data(self.vessel)["voyage"]["destination"])

    def test_imported_changed_return_to_origin_is_visible_and_survives_repeated_exports(self):
        for hours, destination in ((1, "BONGA"), (2, PORT["name"]), (3, PORT["name"])):
            moment = START + timedelta(hours=hours)
            import_report(self.report(when=moment, latitude=5.0, destination=destination), now=moment)
            self.vessel.refresh_from_db()
            payload = vessel_data(self.vessel)["voyage"]
            self.assertEqual(payload["status"], "underway")
            self.assertEqual(payload["origin"], PORT)
            self.assertEqual(payload["destination"], {"name": "BONGA"} if hours == 1 else PORT)
        before = deepcopy(self.vessel.voyage_state)
        for hours in (1, 3):
            import_report(self.report(when=START + timedelta(hours=hours), latitude=5.0, destination="BONGA"),
                          now=START + timedelta(hours=4))
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.voyage_state, before)
        self.assertEqual(vessel_data(self.vessel)["voyage"]["destination"], PORT)

    def test_repeated_unchanged_origin_in_new_exports_is_still_suppressed(self):
        for hours in (1, 2, 3):
            moment = START + timedelta(hours=hours)
            import_report(self.report(when=moment, latitude=5.0), now=moment)
            self.vessel.refresh_from_db()
            self.assertEqual(vessel_data(self.vessel)["voyage"]["status"], "underway")
            self.assertIsNone(vessel_data(self.vessel)["voyage"]["destination"])

    def test_static_changed_return_to_origin_is_visible_without_inventing_arrival(self):
        departure = START + timedelta(hours=1)
        import_report(self.report(when=departure, latitude=5.0), now=departure)
        for hours, destination in ((2, "BONGA"), (3, PORT["name"]), (4, PORT["name"])):
            self.static(START + timedelta(hours=hours), Destination=destination)
            self.vessel.refresh_from_db()
            payload = vessel_data(self.vessel)["voyage"]
            self.assertEqual(payload["status"], "underway")
            self.assertEqual(payload["position_timestamp"], departure.isoformat())
            self.assertEqual(payload["destination"], {"name": "BONGA"} if hours == 2 else PORT)
        before = deepcopy(self.vessel.voyage_state)
        for hours in (2, 4):
            self.static(START + timedelta(hours=hours), Destination="BONGA")
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.voyage_state, before)
        self.assertEqual(vessel_data(self.vessel)["voyage"]["destination"], PORT)

    def test_repeated_unchanged_origin_in_new_static_messages_is_still_suppressed(self):
        departure = START + timedelta(hours=1)
        import_report(self.report(when=departure, latitude=5.0), now=departure)
        self.vessel.refresh_from_db()
        before = deepcopy(self.vessel.voyage_state)
        for hours in (2, 3):
            self.static(START + timedelta(hours=hours), Destination=PORT["name"])
            self.vessel.refresh_from_db()
            self.assertEqual(self.vessel.voyage_state, before)
            self.assertIsNone(vessel_data(self.vessel)["voyage"]["destination"])

    def test_position_inside_circle_marks_arrived_even_if_declared_target_is_elsewhere(self):
        departure = START + timedelta(hours=1)
        arrival = START + timedelta(hours=3)
        import_report(self.report(when=departure, latitude=5.0, destination="BONGA"), now=departure)
        import_report(self.report(when=arrival, destination="BONGA"), now=arrival)
        self.vessel.refresh_from_db()
        payload = vessel_data(self.vessel)["voyage"]
        self.assertEqual(payload["status"], "arrived")
        self.assertEqual(payload["current_port"], PORT)
        self.assertEqual(payload["destination"], PORT)
        self.assertEqual(self.vessel.destination, "BONGA")


@override_settings(AIS_PORT_GEOFENCES=[PORT, BONGA], AIS_VESSEL_SHUTTLE_ROUTES=SHUTTLE_ROUTES)
class ShuttleRouteTests(SimpleTestCase):
    def vessel(self, **kwargs):
        vessel = current_vessel(**kwargs)
        vessel.mmsi = SHUTTLE_MMSI
        return vessel

    def test_arrived_at_aveon_retains_arrival_and_shows_bonga_as_next_destination(self):
        payload = voyage_payload(self.vessel())
        self.assertEqual(payload["status"], "arrived")
        self.assertEqual(payload["current_port"], PORT)
        self.assertEqual(payload["destination"], PORT)
        self.assertEqual(payload["destination_source"], "arrival")
        self.assertEqual(payload["next_destination"], BONGA)
        self.assertEqual(payload["route_ports"], [PORT, BONGA])
        self.assertEqual(payload["arrived_at"], START.isoformat())

    def test_outbound_route_uses_bonga_even_if_ais_still_declares_aveon(self):
        moment = START + timedelta(hours=1)
        state = advance(advance(), when=moment, latitude=5.0)
        payload = voyage_payload(self.vessel(state=state, latitude=5.0, when=moment))
        self.assertEqual(payload["status"], "underway")
        self.assertEqual(payload["origin"], PORT)
        self.assertEqual(payload["destination"], BONGA)
        self.assertEqual(payload["destination_source"], "scheduled_route")
        self.assertIsNone(payload["next_destination"])

    def test_bonga_arrival_and_departure_reverse_only_the_observed_direction(self):
        arrival = START + timedelta(hours=6)
        state = advance(advance(), when=arrival, latitude=BONGA["latitude"], longitude=BONGA["longitude"],
                        geofences=[PORT, BONGA])
        vessel = self.vessel(state=state, latitude=BONGA["latitude"], longitude=BONGA["longitude"], when=arrival)
        payload = voyage_payload(vessel)
        self.assertEqual(payload["current_port"], BONGA)
        self.assertEqual(payload["destination"], BONGA)
        self.assertEqual(payload["next_destination"], PORT)
        self.assertEqual(payload["origin"], PORT)
        departed_at = arrival + timedelta(hours=2)
        state = advance(state, when=departed_at, latitude=4.7, longitude=5.5, geofences=[PORT, BONGA])
        payload = voyage_payload(self.vessel(state=state, latitude=4.7, longitude=5.5, when=departed_at,
                                             destination=BONGA["name"]))
        self.assertEqual(payload["status"], "underway")
        self.assertEqual(payload["origin"], BONGA)
        self.assertEqual(payload["destination"], PORT)
        self.assertEqual(payload["destination_source"], "scheduled_route")

    def test_unknown_departure_does_not_invent_origin_for_outbound_target(self):
        payload = voyage_payload(self.vessel(latitude=4.7, longitude=5.5))
        self.assertEqual(payload["status"], "underway")
        self.assertIsNone(payload["origin"])
        self.assertIsNone(payload["departed_at"])
        self.assertEqual(payload["destination"], BONGA)
        self.assertEqual(payload["destination_source"], "scheduled_route")

    def test_missing_position_keeps_unknown_status_and_never_claims_arrival(self):
        payload = voyage_payload(self.vessel(latitude=None, longitude=None, when=None))
        self.assertEqual(payload["status"], "unknown")
        self.assertIsNone(payload["current_port"])
        self.assertIsNone(payload["origin"])
        self.assertIsNone(payload["arrived_at"])
        self.assertEqual(payload["destination"], BONGA)

    def test_bonga_coordinates_use_latitude_then_longitude_without_rounding_or_swapping(self):
        correct = voyage_payload(self.vessel(latitude=4.5575266, longitude=4.6164432))
        swapped = voyage_payload(self.vessel(latitude=4.6164432, longitude=4.5575266))
        self.assertEqual(correct["current_port"], BONGA)
        self.assertEqual(correct["current_port"]["latitude"], 4.5575266)
        self.assertEqual(correct["current_port"]["longitude"], 4.6164432)
        self.assertEqual(swapped["status"], "underway")
        self.assertIsNone(swapped["current_port"])

    def test_other_mmsi_keeps_declared_destination_and_stale_origin_rules(self):
        moment = START + timedelta(hours=1)
        state = advance(advance(), when=moment, latitude=5.0)
        vessel = current_vessel(state=state, latitude=5.0, when=moment)
        vessel.mmsi = "123456789"
        payload = voyage_payload(vessel)
        self.assertIsNone(payload["destination"])
        self.assertIsNone(payload["destination_source"])
        self.assertEqual(payload["route_ports"], [])
        vessel.destination = BONGA["name"]
        payload = voyage_payload(vessel)
        self.assertEqual(payload["destination"], BONGA)
        self.assertEqual(payload["destination_source"], "ais_declared")
        self.assertIsNone(payload["next_destination"])

    def test_missing_route_endpoint_does_not_create_an_incomplete_fixed_route(self):
        payload = voyage_payload(self.vessel(), geofences=[PORT])
        self.assertEqual(payload["route_ports"], [])
        self.assertIsNone(payload["next_destination"])


@override_settings(AIS_PORT_GEOFENCES=[PORT, BONGA], AIS_VESSEL_SHUTTLE_ROUTES=SHUTTLE_ROUTES)
class ShuttleImportTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi=SHUTTLE_MMSI, name="EASTERN URSINIA",
                                            destination=PORT["name"], last_latitude=PORT["latitude"],
                                            last_longitude=PORT["longitude"], last_seen=START)

    def observation(self, hours, latitude, longitude, destination=PORT["name"]):
        moment = START + timedelta(hours=hours)
        report = ("MMSI,LAT,LON,TIMESTAMP,DESTINATION\n"
                  f"{SHUTTLE_MMSI},{latitude},{longitude},{moment.isoformat()},{destination}\n")
        import_report(report, now=START + timedelta(days=1))
        self.vessel.refresh_from_db()
        return vessel_data(self.vessel)["voyage"]

    def test_imports_track_both_shuttle_directions_and_preserve_previous_positions(self):
        outbound = self.observation(1, 4.7, 5.5)
        self.assertEqual(outbound["origin"], PORT)
        self.assertEqual(outbound["destination"], BONGA)
        arrival = self.observation(6, BONGA["latitude"], BONGA["longitude"])
        self.assertEqual(arrival["status"], "arrived")
        self.assertEqual(arrival["next_destination"], PORT)
        returning = self.observation(8, 4.7, 5.5, destination=BONGA["name"])
        self.assertEqual(returning["origin"], BONGA)
        self.assertEqual(returning["destination"], PORT)
        before = list(self.vessel.positions.values())
        self.observation(9, PORT["latitude"], PORT["longitude"])
        self.assertEqual(list(self.vessel.positions.filter(timestamp__lt=START + timedelta(hours=9)).values()), before)
        self.assertEqual(vessel_data(self.vessel)["voyage"]["next_destination"], BONGA)

    def test_old_and_duplicate_exports_cannot_reverse_current_trip(self):
        self.observation(6, BONGA["latitude"], BONGA["longitude"])
        self.observation(8, 4.7, 5.5)
        before = deepcopy(self.vessel.voyage_state)
        for hours in (3, 8):
            payload = self.observation(hours, PORT["latitude"], PORT["longitude"], destination=BONGA["name"])
            self.assertEqual(self.vessel.voyage_state, before)
            self.assertEqual(payload["status"], "underway")
            self.assertEqual(payload["origin"], BONGA)
            self.assertEqual(payload["destination"], PORT)

    def test_live_ais_port_calls_use_the_same_shuttle_direction(self):
        for hours, latitude, longitude in ((6, BONGA["latitude"], BONGA["longitude"]), (8, 4.7, 5.5)):
            moment = START + timedelta(hours=hours)
            message = position_frame(UserID=int(SHUTTLE_MMSI), Latitude=latitude, Longitude=longitude)
            message["MetaData"].update(MMSI=int(SHUTTLE_MMSI), time_utc=moment.isoformat())
            ingest_ais_message(message, now=START + timedelta(days=1))
            self.vessel.refresh_from_db()
            payload = vessel_data(self.vessel)["voyage"]
            if hours == 6:
                self.assertEqual(payload["current_port"], BONGA)
                self.assertEqual(payload["next_destination"], PORT)
            else:
                self.assertEqual(payload["status"], "underway")
                self.assertEqual(payload["origin"], BONGA)
                self.assertEqual(payload["destination"], PORT)

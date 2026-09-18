import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from apps.vessels.imports import ReportError, import_report, parse_coordinate, parse_report, parse_timestamp
from apps.vessels.models import Vessel, VesselPosition


MMSI = "636023616"
NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
RECENT = NOW - timedelta(minutes=4)


def report(rows, header="MMSI,SHIPNAME,LAT,LON,SPEED,COURSE,HEADING,TIMESTAMP,DESTINATION"):
    return "\n".join([header, *rows]) + "\n"


def row(timestamp=RECENT, mmsi=MMSI, lat="4.18291", lon="6.81921", speed="11.3",
        course="223.0", heading="224", name="EASTERN URSINIA", destination="ONNE"):
    moment = timestamp.strftime("%Y-%m-%d %H:%M:%S") if hasattr(timestamp, "strftime") else timestamp
    return ",".join([mmsi, name, lat, lon, speed, course, heading, moment, destination])


class ParseTimestampTests(SimpleTestCase):
    def test_accepts_common_layouts(self):
        expected = datetime(2026, 9, 16, 10, 15, tzinfo=timezone.utc)
        for value in ("2026-09-16 10:15:00", "2026-09-16T10:15:00Z", "2026-09-16 10:15 UTC",
                      "16/09/2026 10:15", "2026-09-16T10:15:00+00:00"):
            with self.subTest(value=value):
                self.assertEqual(parse_timestamp(value), expected)

    def test_converts_offset_to_utc(self):
        self.assertEqual(parse_timestamp("2026-09-16T12:15:00+02:00"),
                         datetime(2026, 9, 16, 10, 15, tzinfo=timezone.utc))

    def test_accepts_epoch_seconds_and_milliseconds(self):
        moment = datetime(2026, 9, 16, 10, 15, tzinfo=timezone.utc)
        epoch = int(moment.timestamp())
        self.assertEqual(parse_timestamp(str(epoch)), moment)
        self.assertEqual(parse_timestamp(str(epoch * 1000)), moment)

    def test_rejects_placeholders_and_garbage(self):
        for value in ("", "-", "N/A", "unknown", "not a date", None):
            with self.subTest(value=value):
                self.assertIsNone(parse_timestamp(value))


class ParseCoordinateTests(SimpleTestCase):
    def test_reads_decimal_and_hemisphere(self):
        self.assertEqual(parse_coordinate("4.18291", limit=90), 4.18291)
        self.assertEqual(parse_coordinate("-4.18291", limit=90), -4.18291)
        self.assertEqual(parse_coordinate("4.18291 S", limit=90), -4.18291)
        self.assertEqual(parse_coordinate("6.81921 W", limit=180), -6.81921)
        self.assertEqual(parse_coordinate("6,81921", limit=180), 6.81921)

    def test_rejects_out_of_range_and_unparseable(self):
        for value, limit in (("91.5", 90), ("181.2", 180), ("abc", 90), ("", 90)):
            with self.subTest(value=value):
                self.assertIsNone(parse_coordinate(value, limit=limit))


class ParseReportTests(SimpleTestCase):
    def test_reads_a_valid_row(self):
        result = parse_report(report([row()]), now=NOW)
        self.assertEqual(result.parsed, 1)
        observation = result.observations[0]
        self.assertEqual(observation["mmsi"], MMSI)
        self.assertAlmostEqual(observation["latitude"], 4.18291)
        self.assertAlmostEqual(observation["longitude"], 6.81921)
        self.assertEqual(observation["sog"], 11.3)
        self.assertEqual(observation["age_seconds"], 240)

    def test_matches_alternative_column_names(self):
        text = report([",".join([MMSI, "4.18291", "6.81921", "2026-09-16 11:56:00"])],
                      header="Ship MMSI,Latitude,Longitude,Position Received")
        result = parse_report(text, now=NOW)
        self.assertEqual(result.parsed, 1)
        self.assertEqual(result.observations[0]["mmsi"], MMSI)

    def test_handles_semicolon_delimiter(self):
        text = "MMSI;LAT;LON;TIMESTAMP\n" + ";".join([MMSI, "4.18291", "6.81921", "2026-09-16 11:56:00"]) + "\n"
        self.assertEqual(parse_report(text, now=NOW).parsed, 1)

    def test_reading_a_semicolon_report_does_not_break_the_next_comma_report(self):
        # csv.excel is a class; mutating its delimiter would leak across every later read.
        semicolon = "sep=;\r\nMMSI;LAT;LON;TIMESTAMP\r\n" + ";".join([MMSI, "4.18291", "6.81921", "2026-09-16 11:56:00"]) + "\r\n"
        self.assertEqual(parse_report(semicolon, now=NOW).parsed, 1)
        self.assertEqual(parse_report(report([row()]), now=NOW).parsed, 1)
        self.assertEqual(csv.excel.delimiter, ",")

    def test_skips_provider_preamble_before_the_header(self):
        text = "Exported by provider\nGenerated 2026-09-16\n\n" + report([row()])
        self.assertEqual(parse_report(text, now=NOW).parsed, 1)

    def test_rejects_null_island_and_out_of_range_positions(self):
        text = report([row(lat="0", lon="0"), row(lat="91", lon="181")])
        result = parse_report(text, now=NOW)
        self.assertEqual(result.parsed, 0)
        self.assertEqual(result.skipped, 2)
        self.assertIn("position unavailable", result.issues[0].reason)
        self.assertIn("unreadable coordinates", result.issues[1].reason)

    def test_drops_speed_and_heading_sentinels_but_keeps_the_position(self):
        result = parse_report(report([row(speed="102.3", course="360", heading="511")]), now=NOW)
        observation = result.observations[0]
        self.assertIsNone(observation["sog"])
        self.assertIsNone(observation["cog"])
        self.assertIsNone(observation["heading"])
        self.assertAlmostEqual(observation["latitude"], 4.18291)

    def test_skips_future_timestamps(self):
        result = parse_report(report([row(timestamp=NOW + timedelta(hours=2))]), now=NOW)
        self.assertEqual(result.parsed, 0)
        self.assertIn("future", result.issues[0].reason)

    def test_skips_rows_without_identity_or_coordinates(self):
        result = parse_report(report([row(mmsi="123"), row(lat="abc")]), now=NOW)
        self.assertEqual(result.parsed, 0)
        self.assertEqual(result.skipped, 2)

    def test_rejects_a_file_without_a_usable_header(self):
        for text in ("name,port\nfoo,bar\n", "   "):
            with self.subTest(text=text):
                with self.assertRaises(ReportError):
                    parse_report(text, now=NOW)


class ImportReportTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi=MMSI, name="EASTERN URSINIA", imo="9698458")

    def test_stores_position_and_advances_the_vessel(self):
        result = import_report(report([row()]), now=NOW)
        self.assertEqual((result.created, result.vessels_advanced), (1, 1))
        position = VesselPosition.objects.get()
        self.assertEqual(position.source, "AIS")
        self.assertEqual(position.provider, "marinetraffic_report")
        self.vessel.refresh_from_db()
        self.assertAlmostEqual(self.vessel.last_latitude, 4.18291)
        self.assertEqual(self.vessel.last_seen, RECENT)
        self.assertEqual(self.vessel.last_provider, "marinetraffic_report")
        self.assertEqual(self.vessel.destination, "ONNE")

    def test_reimporting_the_same_report_changes_nothing(self):
        text = report([row()])
        import_report(text, now=NOW)
        result = import_report(text, now=NOW)
        self.assertEqual((result.created, result.duplicates), (0, 1))
        self.assertEqual(VesselPosition.objects.count(), 1)

    def test_never_moves_the_vessel_backwards(self):
        import_report(report([row()]), now=NOW)
        older = RECENT - timedelta(hours=6)
        result = import_report(report([row(timestamp=older, lat="1.0", lon="2.0")]), now=NOW)
        self.assertEqual(result.created, 1)
        self.assertEqual(result.vessels_advanced, 0)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_seen, RECENT)
        self.assertAlmostEqual(self.vessel.last_latitude, 4.18291)

    def test_ignores_vessels_that_are_not_registered(self):
        result = import_report(report([row(mmsi="123456789")]), now=NOW)
        self.assertEqual(result.created, 0)
        self.assertEqual(VesselPosition.objects.count(), 0)
        self.assertIn("not a registered vessel", result.issues[0].reason)

    def test_matches_by_imo_when_mmsi_is_absent(self):
        text = report([",".join(["9698458", "4.5", "6.5", "2026-09-16 11:56:00"])],
                      header="IMO,LAT,LON,TIMESTAMP")
        result = import_report(text, now=NOW)
        self.assertEqual(result.created, 1)
        self.assertEqual(VesselPosition.objects.get().vessel_id, self.vessel.pk)

    def test_dry_run_writes_nothing(self):
        result = import_report(report([row()]), now=NOW, dry_run=True)
        self.assertEqual(result.parsed, 1)
        self.assertEqual(VesselPosition.objects.count(), 0)
        self.vessel.refresh_from_db()
        self.assertIsNone(self.vessel.last_seen)

    def test_dry_run_excludes_vessels_outside_the_fleet(self):
        result = import_report(report([row(), row(mmsi="111222333")]), now=NOW, dry_run=True)
        self.assertEqual(result.parsed, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.observations[0]["mmsi"], MMSI)
        self.assertIn("not a registered vessel", result.issues[0].reason)

    def test_rejects_an_invalid_provider_label(self):
        with self.assertRaises(ReportError):
            import_report(report([row()]), provider="bad provider!", now=NOW)

    def test_stores_multiple_rows_in_chronological_order(self):
        rows = [row(timestamp=RECENT - timedelta(minutes=step), lat=str(4.0 + step / 100))
                for step in (30, 20, 10, 0)]
        result = import_report(report(rows), now=NOW)
        self.assertEqual(result.created, 4)
        self.vessel.refresh_from_db()
        self.assertEqual(self.vessel.last_seen, RECENT)


class ImportCommandTests(TestCase):
    """The command uses the real clock, so its rows are built relative to now."""

    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi=MMSI, name="EASTERN URSINIA")
        self.now = django_timezone.now()

    def run_command(self, text, *args):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            path.write_text(text, encoding="utf-8")
            out, err = StringIO(), StringIO()
            call_command("import_vessel_report", str(path), *args, stdout=out, stderr=err)
            return out.getvalue()

    def test_imports_and_reports_position_age(self):
        output = self.run_command(report([row(timestamp=self.now - timedelta(minutes=4))]))
        self.assertIn("1 valid observation", output)
        self.assertIn(MMSI, output)
        self.assertIn("Stored 1 new position", output)
        self.assertEqual(VesselPosition.objects.count(), 1)

    def test_dry_run_reports_without_storing(self):
        output = self.run_command(report([row(timestamp=self.now - timedelta(minutes=4))]), "--dry-run")
        self.assertIn("DRY RUN", output)
        self.assertEqual(VesselPosition.objects.count(), 0)

    def test_warns_when_the_report_is_stale(self):
        output = self.run_command(report([row(timestamp=self.now - timedelta(days=47))]))
        self.assertIn("does not make the position current", output)

    def test_max_age_hours_refuses_a_stale_report(self):
        with self.assertRaises(CommandError) as caught:
            self.run_command(report([row(timestamp=self.now - timedelta(days=47))]), "--max-age-hours", "24")
        self.assertIn("not current", str(caught.exception))

    def test_missing_file_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command("import_vessel_report", "no-such-report.csv", stdout=StringIO())

    def test_unusable_report_is_an_error(self):
        with self.assertRaises(CommandError):
            self.run_command("name,port\nfoo,bar\n")

"""Import a provider position report (CSV) into the registered fleet.

The report's own timestamps decide freshness: every imported observation is
reported with its real age so a stale export is visible instead of silently
becoming the vessel's current position.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vessels.imports import DEFAULT_PROVIDER, ReportError, import_report


ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
MAX_BYTES = 32 * 1024 * 1024


def describe_age(seconds: int) -> str:
    if seconds < 90:
        return str(seconds) + "s ago"
    if seconds < 5400:
        return str(round(seconds / 60)) + " min ago"
    if seconds < 172800:
        return str(round(seconds / 3600, 1)) + " h ago"
    return str(round(seconds / 86400, 1)) + " days ago"


class Command(BaseCommand):
    help = ("Import real AIS positions from a provider report export (CSV/TSV) for vessels already "
            "registered in the fleet. Re-importing the same report is safe and changes nothing.")

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the report file exported by the provider.")
        parser.add_argument("--provider", default=DEFAULT_PROVIDER,
                            help="Channel that delivered the report; stored for auditing (default: %(default)s).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and report what would be imported without writing anything.")
        parser.add_argument("--max-age-hours", type=float, default=None,
                            help="Refuse to import observations older than this many hours.")

    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser()
        if not path.is_file():
            raise CommandError("Report file not found: " + str(path))
        if path.stat().st_size > MAX_BYTES:
            raise CommandError("Report file is larger than 32 MB; export a narrower date range.")
        text = None
        for encoding in ENCODINGS:
            try:
                text = path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            raise CommandError("Could not decode the report file; save it as UTF-8 CSV and retry.")

        try:
            result = import_report(text, provider=options["provider"], dry_run=options["dry_run"])
        except ReportError as exc:
            raise CommandError(str(exc)) from exc

        recent = max(0, int(getattr(settings, "AIS_RECENT_SECONDS", 600)))
        stale = max(recent, int(getattr(settings, "AIS_STALE_SECONDS", 3600)))
        limit = options["max_age_hours"]
        mode = "DRY RUN - nothing was written" if options["dry_run"] else "Imported"
        self.stdout.write(mode + ": " + str(result.parsed) + " valid observation(s) read from " + path.name)

        # Freshness of a report is decided by its most recent fix, not its oldest.
        freshest = None
        for observation in sorted(result.observations, key=lambda item: item["timestamp"]):
            age = observation["age_seconds"]
            freshest = age if freshest is None else min(freshest, age)
            label = "RECENT" if age <= recent else "STALE" if age <= stale else "NO RECENT AIS"
            style = self.style.SUCCESS if age <= recent else self.style.WARNING if age <= stale else self.style.ERROR
            self.stdout.write("  " + (observation["mmsi"] or observation["imo"]) + "  "
                              + observation["timestamp"].isoformat() + "  "
                              + format(observation["latitude"], ".5f") + ", "
                              + format(observation["longitude"], ".5f") + "  "
                              + style(label + " (" + describe_age(age) + ")"))

        if not options["dry_run"]:
            self.stdout.write("Stored " + str(result.created) + " new position(s); "
                              + str(result.duplicates) + " already present; "
                              + str(result.vessels_advanced) + " vessel(s) moved forward.")
        if result.skipped:
            self.stdout.write(self.style.WARNING("Skipped " + str(result.skipped) + " row(s):"))
            for issue in result.issues[:20]:
                self.stdout.write("  - " + str(issue))
            if len(result.issues) > 20:
                self.stdout.write("  ... and " + str(len(result.issues) - 20) + " more.")
        if not result.parsed:
            raise CommandError("No valid observation was found in the report.")
        if limit is not None and freshest is not None and freshest > limit * 3600:
            raise CommandError("The most recent observation is " + describe_age(freshest)
                               + ", beyond the --max-age-hours limit. The report is not current.")
        if freshest is not None and freshest > stale:
            self.stdout.write(self.style.WARNING(
                "The most recent position in this report is " + describe_age(freshest)
                + ". The provider has no recent fix for this vessel; importing it does not make the position current."))

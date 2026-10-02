from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.engineering_monitor_import import import_engineering_monitor_workbook
from apps.core.models import EngineeringMonitorImport


class Command(BaseCommand):
    help = "Load the Engineering MDR workbook using the same importer as the dashboard."

    def add_arguments(self, parser):
        parser.add_argument("workbook", type=Path)
        parser.add_argument(
            "--initial-only", action="store_true",
            help="Preserve an existing active MDR; replace only an empty or legacy engineering source.",
        )

    def handle(self, *args, **options):
        if options["initial_only"] and EngineeringMonitorImport.objects.filter(
            is_active=True, metadata__import_mode="mdr_engineering",
        ).exists():
            self.stdout.write("An active Engineering MDR already exists; no data changed.")
            return
        try:
            with options["workbook"].open("rb") as workbook:
                batch = import_engineering_monitor_workbook(workbook, require_mdr=True)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Imported {batch.document_count} MDR documents across "
            f"{batch.discipline_count} disciplines (import #{batch.pk})."
        ))

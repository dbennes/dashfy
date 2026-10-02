from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from apps.core.fabrication_batches import import_workbook


class Command(BaseCommand):
    help = 'Import the SPS priority / Dummy Spools workbook for the batch chart.'

    def add_arguments(self, parser):
        parser.add_argument('workbook', type=Path)

    def handle(self, *args, **options):
        try:
            with options['workbook'].open('rb') as upload:
                snapshot = import_workbook(upload)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Imported {snapshot.payload['scopes']['all']['item_count']} listed items."))

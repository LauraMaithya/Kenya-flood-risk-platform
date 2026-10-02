from django.core.management.base import BaseCommand, CommandError

from monitoring.services.observation_ingestion import (
    ObservationIngestionError,
    ingest_observations,
)


class Command(BaseCommand):
    help = "Import county environmental observations from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the environmental-observation CSV file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the file without saving database changes.",
        )

    def handle(self, *args, **options):
        try:
            summary = ingest_observations(
                csv_path=options["file"],
                dry_run=options["dry_run"],
            )
        except ObservationIngestionError as exc:
            raise CommandError(str(exc)) from exc

        mode = "DRY RUN" if summary.dry_run else "IMPORT"

        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} completed: "
                f"{summary.processed} processed, "
                f"{summary.created} created, "
                f"{summary.updated} updated, "
                f"{summary.counties_created} counties created."
            )
        )
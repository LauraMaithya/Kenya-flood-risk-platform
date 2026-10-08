from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from monitoring.services.observation_ingestion import (
    ObservationIngestionError,
    ingest_observations,
)


DEFAULT_BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Import county environmental observations "
        "from a CSV file."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help=(
                "Path to the environmental-observation "
                "CSV file."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Validate the file without saving "
                "database changes."
            ),
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=(
                "Number of observations written in each "
                f"database batch. Default: "
                f"{DEFAULT_BATCH_SIZE}."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]

        if batch_size <= 0:
            raise CommandError(
                "--batch-size must be greater than zero."
            )

        try:
            summary = ingest_observations(
                csv_path=options["file"],
                dry_run=options["dry_run"],
                batch_size=batch_size,
            )
        except ObservationIngestionError as exc:
            raise CommandError(str(exc)) from exc

        mode = (
            "DRY RUN"
            if summary.dry_run
            else "IMPORT"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} completed: "
                f"{summary.processed} processed, "
                f"{summary.created} created, "
                f"{summary.updated} updated, "
                f"{summary.counties_created} "
                "counties created."
            )
        )
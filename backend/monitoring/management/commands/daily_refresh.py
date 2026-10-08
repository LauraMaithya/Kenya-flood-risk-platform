from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from monitoring.services.daily_refresh import (
    DailyRefreshError,
    run_daily_refresh,
)


DEFAULT_BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Ingest observations, generate predictions, "
        "and optionally create High-risk alerts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help=(
                "Path to the daily environmental-"
                "observation CSV file."
            ),
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=(
                "Number of observations processed in "
                f"each database batch. Default: "
                f"{DEFAULT_BATCH_SIZE}."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Validate and roll back ingestion without "
                "generating predictions or alerts."
            ),
        )
        parser.add_argument(
            "--alert-channel",
            choices=["IN_APP", "EMAIL"],
            help=(
                "Optional alert channel for High-risk "
                "predictions."
            ),
        )
        parser.add_argument(
            "--alert-recipient",
            help=(
                "Optional recipient used with "
                "--alert-channel."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]

        if batch_size <= 0:
            raise CommandError(
                "--batch-size must be greater than zero."
            )

        try:
            summary = run_daily_refresh(
                options["file"],
                batch_size=batch_size,
                dry_run=options["dry_run"],
                alert_channel=options[
                    "alert_channel"
                ],
                alert_recipient=options[
                    "alert_recipient"
                ],
            )
        except DailyRefreshError as exc:
            raise CommandError(str(exc)) from exc

        mode = (
            "DRY RUN"
            if summary.dry_run
            else "REFRESH"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} completed: "
                f"{summary.observations_processed} "
                "observations processed, "
                f"{summary.observations_created} created, "
                f"{summary.observations_updated} updated; "
                f"{summary.predictions_created} "
                "predictions created, "
                f"{summary.predictions_existing} existing; "
                f"{summary.high_risk_predictions} "
                "High-risk predictions; "
                f"{summary.alerts_created} alerts created, "
                f"{summary.alerts_existing} existing."
            )
        )
from datetime import date

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.utils import timezone

from monitoring.models import County
from monitoring.services.open_meteo_refresh import (
    OpenMeteoRefreshError,
    refresh_open_meteo_county,
)


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = (
        "Fetch Open-Meteo data, store live telemetry, "
        "create environmental observations, and generate "
        "flood-risk predictions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="observation_date",
            help=(
                "Observation date in YYYY-MM-DD format. "
                "Defaults to the current local date."
            ),
        )
        parser.add_argument(
            "--county-code",
            help=(
                "Refresh one county using its code. "
                "If omitted, all counties are refreshed."
            ),
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Open-Meteo request timeout in seconds.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Fetch and validate data without permanently "
                "saving records or predictions."
            ),
        )

    def handle(self, *args, **options):
        observation_date = self._observation_date(
            options["observation_date"]
        )
        timeout = options["timeout"]
        dry_run = options["dry_run"]

        if timeout <= 0:
            raise CommandError(
                "The timeout must be greater than zero."
            )

        counties = County.objects.order_by(
            "code"
        )

        county_code = options.get("county_code")

        if county_code:
            counties = counties.filter(
                code=county_code
            )

            if not counties.exists():
                raise CommandError(
                    f"Unknown county code: {county_code}"
                )

        county_count = counties.count()

        if county_count == 0:
            raise CommandError(
                "No counties are available for refresh."
            )

        totals = {
            "devices_created": 0,
            "readings_created": 0,
            "readings_updated": 0,
            "observations_created": 0,
            "observations_updated": 0,
            "observations_preserved": 0,
            "predictions_created": 0,
            "predictions_existing": 0,
        }

        for county in counties.iterator():
            try:
                summary = refresh_open_meteo_county(
                    county,
                    observation_date=observation_date,
                    timeout=timeout,
                    dry_run=dry_run,
                )
            except OpenMeteoRefreshError as exc:
                raise CommandError(str(exc)) from exc

            totals["devices_created"] += int(
                summary.device_created
            )
            totals["readings_created"] += int(
                summary.reading_created
            )
            totals["readings_updated"] += int(
                summary.reading_updated
            )
            totals["observations_created"] += int(
                summary.observation_created
            )
            totals["observations_updated"] += int(
                summary.observation_updated
            )
            totals["observations_preserved"] += int(
                summary.observation_preserved
            )
            totals["predictions_created"] += int(
                summary.prediction_created
            )
            totals["predictions_existing"] += int(
                summary.prediction_existing
            )

            self.stdout.write(
                self._county_message(summary)
            )

        run_status = (
            "DRY RUN"
            if dry_run
            else "COMPLETED"
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Open-Meteo refresh "
                f"{run_status}: "
                f"{county_count} counties, "
                f"{totals['devices_created']} devices created, "
                f"{totals['readings_created']} readings created, "
                f"{totals['readings_updated']} readings updated, "
                f"{totals['observations_created']} observations "
                "created, "
                f"{totals['observations_updated']} observations "
                "updated, "
                f"{totals['observations_preserved']} observations "
                "preserved, "
                f"{totals['predictions_created']} predictions "
                "created, "
                f"{totals['predictions_existing']} predictions "
                "existing."
            )
        )

    @staticmethod
    def _observation_date(value):
        if value:
            return parse_date(value)

        return timezone.localdate()

    @staticmethod
    def _county_message(summary):
        return (
            f"{summary.county_code} "
            f"{summary.county_name}: "
            f"{summary.observation_date}, "
            f"device created={summary.device_created}, "
            f"reading created={summary.reading_created}, "
            f"reading updated={summary.reading_updated}, "
            f"observation created="
            f"{summary.observation_created}, "
            f"observation updated="
            f"{summary.observation_updated}, "
            f"observation preserved="
            f"{summary.observation_preserved}, "
            f"prediction created="
            f"{summary.prediction_created}, "
            f"prediction existing="
            f"{summary.prediction_existing}."
        )
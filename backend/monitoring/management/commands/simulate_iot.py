from datetime import datetime

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.utils import timezone

from monitoring.models import County
from monitoring.services.simulated_iot_refresh import (
    SimulatedIoTRefreshError,
    refresh_simulated_iot_county,
)


def parse_recorded_at(value):
    normalized = value.replace(
        "Z",
        "+00:00",
    )

    try:
        recorded_at = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise CommandError(
            "Invalid recorded time. Use ISO 8601, for example "
            "2026-10-23T15:00:00+03:00."
        ) from exc

    if timezone.is_naive(recorded_at):
        raise CommandError(
            "The recorded time must include a timezone offset."
        )

    return recorded_at


class Command(BaseCommand):
    help = (
        "Generate historically calibrated simulated IoT "
        "telemetry for one or more counties."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--recorded-at",
            help=(
                "ISO 8601 packet time including timezone. "
                "Defaults to the current time."
            ),
        )
        parser.add_argument(
            "--county-code",
            help=(
                "Simulate one county using its code. "
                "If omitted, all counties are simulated."
            ),
        )
        parser.add_argument(
            "--seed",
            help=(
                "Optional deterministic simulation seed."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Generate and validate packets without "
                "permanently saving them."
            ),
        )

    def handle(self, *args, **options):
        recorded_at = self._recorded_at(
            options.get("recorded_at")
        )
        county_code = options.get("county_code")
        seed = options.get("seed")
        dry_run = options["dry_run"]

        counties = County.objects.order_by(
            "code"
        )

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
                "No counties are available for simulation."
            )

        totals = {
            "devices_created": 0,
            "readings_created": 0,
            "readings_updated": 0,
        }

        for county in counties.iterator():
            try:
                summary = refresh_simulated_iot_county(
                    county,
                    recorded_at=recorded_at,
                    seed=seed,
                    dry_run=dry_run,
                )
            except SimulatedIoTRefreshError as exc:
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
                "Simulated IoT refresh "
                f"{run_status}: "
                f"{county_count} counties, "
                f"{totals['devices_created']} devices created, "
                f"{totals['readings_created']} readings created, "
                f"{totals['readings_updated']} readings updated."
            )
        )

    @staticmethod
    def _recorded_at(value):
        if value:
            return parse_recorded_at(value)

        return timezone.now()

    @staticmethod
    def _county_message(summary):
        return (
            f"{summary.county_code} "
            f"{summary.county_name}: "
            f"recorded at {summary.recorded_at.isoformat()}, "
            f"calibrated from "
            f"{summary.calibration_observation_count} "
            "historical observations, "
            f"reference date "
            f"{summary.calibration_reference_date}, "
            f"device created={summary.device_created}, "
            f"reading created={summary.reading_created}, "
            f"reading updated={summary.reading_updated}."
        )
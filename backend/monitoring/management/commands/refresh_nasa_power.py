from datetime import date, timedelta

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.utils import timezone

from monitoring.models import County
from monitoring.services.nasa_power_prediction import (
    NasaPowerPredictionError,
    predict_missing_nasa_power,
)
from monitoring.services.nasa_power_refresh import (
    NasaPowerDataUnavailable,
    NasaPowerRefreshError,
    refresh_nasa_power_county,
)
from monitoring.services.nasa_power_schedule import (
    NasaPowerScheduleError,
    build_nasa_power_refresh_plan,
)


DEFAULT_START_DATE = date(2026, 1, 1)


def _parse_date(value, option_name):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(
            f"{option_name} must use YYYY-MM-DD format."
        ) from exc


class Command(BaseCommand):
    help = (
        "Automatically fetch, transform and load missing "
        "NASA POWER daily data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            help=(
                "Optional first date in YYYY-MM-DD format. "
                "Default: 2026-01-01."
            ),
        )
        parser.add_argument(
            "--end-date",
            help=(
                "Optional final date in YYYY-MM-DD format. "
                "Default: yesterday."
            ),
        )
        parser.add_argument(
            "--county-code",
            help=(
                "Optional three-digit county code. "
                "If omitted, all NASA-covered counties are used."
            ),
        )
        parser.add_argument(
            "--sample-points",
            type=int,
            default=3,
            help="Interior API points per county. Default: 3.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Timeout for each API request. Default: 30.",
        )
        parser.add_argument(
            "--prediction-batch-size",
            type=int,
            default=1000,
            help=(
                "Number of observations predicted in each batch. "
                "Default: 1000."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Fetch and transform missing data without saving it."
            ),
        )
        parser.add_argument(
            "--plan-only",
            action="store_true",
            help=(
                "Display missing date ranges without making "
                "API requests."
            ),
        )

    def handle(self, *args, **options):
        start_date = (
            _parse_date(
                options["start_date"],
                "--start-date",
            )
            if options.get("start_date")
            else DEFAULT_START_DATE
        )
        end_date = (
            _parse_date(
                options["end_date"],
                "--end-date",
            )
            if options.get("end_date")
            else (
                timezone.localdate()
                - timedelta(days=1)
            )
        )
        sample_points = options["sample_points"]
        timeout = options["timeout"]
        prediction_batch_size = options[
            "prediction_batch_size"
        ]
        dry_run = options["dry_run"]
        plan_only = options["plan_only"]
        county_code = options.get("county_code")

        if start_date > end_date:
            raise CommandError(
                "--start-date must be on or before --end-date."
            )

        if start_date < DEFAULT_START_DATE:
            raise CommandError(
                "This command is limited to NASA POWER data "
                "from 2026 onward."
            )

        if end_date > timezone.localdate():
            raise CommandError(
                "--end-date cannot be in the future."
            )

        if sample_points <= 0:
            raise CommandError(
                "--sample-points must be greater than zero."
            )

        if timeout <= 0:
            raise CommandError(
                "--timeout must be greater than zero."
            )
        if prediction_batch_size <= 0:
            raise CommandError(
                "--prediction-batch-size must be "
                "greater than zero."
            )
        counties = County.objects.filter(
            has_nasa_power_coverage=True,
            latitude__isnull=False,
            longitude__isnull=False,
        ).order_by("name")

        if county_code:
            counties = counties.filter(
                code=county_code
            )

        counties = list(counties)

        if not counties:
            raise CommandError(
                "No matching NASA-covered counties were found."
            )

        try:
            plan = build_nasa_power_refresh_plan(
                counties,
                start_date=start_date,
                end_date=end_date,
            )
        except NasaPowerScheduleError as exc:
            raise CommandError(str(exc)) from exc

        if not plan:
            self.stdout.write(
                self.style.SUCCESS(
                    "NASA POWER data is already current for "
                    f"{start_date} through {end_date}."
                )
            )

            if plan_only or dry_run:
                return

            self._predict_nasa_observations(
                counties,
                start_date=start_date,
                end_date=end_date,
                batch_size=prediction_batch_size,
            )
            return

        total_missing_days = sum(
            item.day_count
            for item in plan
        )

        self.stdout.write(
            "NASA POWER refresh plan: "
            f"{len(counties)} counties checked, "
            f"{len(plan)} missing ranges, "
            f"{total_missing_days} missing county-days."
        )

        for item in plan:
            self.stdout.write(
                f"{item.county_code} "
                f"{item.county_name}: "
                f"{item.start_date} to {item.end_date} "
                f"({item.day_count} days)"
            )

        if plan_only:
            self.stdout.write(
                self.style.SUCCESS(
                    "NASA POWER plan completed without API requests."
                )
            )
            return

        counties_by_id = {
            county.pk: county
            for county in counties
        }
        totals = {
            "ranges": 0,
            "points": 0,
            "days": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "unavailable_ranges": 0,
            "unavailable_days": 0,
        }

        for item in plan:
            county = counties_by_id[
                item.county_id
            ]

            try:
                summary = refresh_nasa_power_county(
                    county,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    sample_point_count=sample_points,
                    timeout=timeout,
                    dry_run=dry_run,
                )
            except NasaPowerDataUnavailable as exc:
                totals["unavailable_ranges"] += 1
                totals["unavailable_days"] += (
                    item.day_count
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"Deferred: {exc}"
                    )
                )
                continue
            except NasaPowerRefreshError as exc:
                raise CommandError(str(exc)) from exc

            totals["ranges"] += 1
            totals["points"] += summary.requested_points
            totals["days"] += summary.county_days
            totals["created"] += (
                summary.observations_created
            )
            totals["updated"] += (
                summary.observations_updated
            )
            totals["unchanged"] += (
                summary.observations_unchanged
            )

            self.stdout.write(
                f"{summary.county_code} "
                f"{summary.county_name}: "
                f"{summary.requested_points} points, "
                f"{summary.county_days} days, "
                f"{summary.observations_created} created, "
                f"{summary.observations_updated} updated, "
                f"{summary.observations_unchanged} unchanged."
            )

        mode = "DRY RUN" if dry_run else "COMPLETED"

        self.stdout.write(
            self.style.SUCCESS(
                f"NASA POWER refresh {mode}: "
                f"{totals['ranges']} ranges, "
                f"{totals['points']} point requests, "
                f"{totals['days']} county-days, "
                f"{totals['created']} created, "
                f"{totals['updated']} updated, "
                f"{totals['unchanged']} unchanged, "
                f"{totals['unavailable_ranges']} ranges "
                f"deferred containing "
                f"{totals['unavailable_days']} county-days."
            )
        )

        if not dry_run:
            self._predict_nasa_observations(
                counties,
                start_date=start_date,
                end_date=end_date,
                batch_size=prediction_batch_size,
            )
    def _predict_nasa_observations(
        self,
        counties,
        *,
        start_date,
        end_date,
        batch_size,
    ):
        try:
            summary = predict_missing_nasa_power(
                counties,
                start_date=start_date,
                end_date=end_date,
                batch_size=batch_size,
            )
        except NasaPowerPredictionError as exc:
            raise CommandError(
                "NASA POWER prediction failed: "
                f"{exc}"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "NASA POWER prediction reconciliation: "
                f"{summary.observations_found} observations, "
                f"{summary.predictions_pending} pending, "
                f"{summary.predictions_created} created, "
                f"{summary.predictions_existing} existing, "
                f"{summary.batches_processed} batches."
            )
        )
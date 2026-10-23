from datetime import date, datetime, timedelta

from django.core.management import call_command
from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.utils import timezone

from monitoring.services.live_alerts import (
    LiveAlertError,
    create_live_high_risk_alerts,
)


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


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
        "Run the complete live data pipeline: reconcile NASA POWER, "
        "refresh Open-Meteo observations and predictions, generate "
        "historically calibrated simulated IoT telemetry, and "
        "optionally create alerts for real live High-risk predictions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="observation_date",
            help=(
                "Live observation date in YYYY-MM-DD format. "
                "Defaults to the current local date."
            ),
        )
        parser.add_argument(
            "--recorded-at",
            help=(
                "ISO 8601 simulated packet time including timezone. "
                "Defaults to the current time."
            ),
        )
        parser.add_argument(
            "--county-code",
            help=(
                "Refresh one county using its three-digit code. "
                "If omitted, all counties are refreshed."
            ),
        )
        parser.add_argument(
            "--sample-points",
            type=int,
            default=3,
            help=(
                "NASA POWER interior API points per county. "
                "Default: 3."
            ),
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help=(
                "Timeout for each external API request. "
                "Default: 30 seconds."
            ),
        )
        parser.add_argument(
            "--prediction-batch-size",
            type=int,
            default=1000,
            help=(
                "NASA POWER prediction reconciliation batch size. "
                "Default: 1000."
            ),
        )
        parser.add_argument(
            "--simulation-seed",
            help=(
                "Optional deterministic seed for simulated IoT "
                "packet generation."
            ),
        )
        parser.add_argument(
            "--alert-channel",
            help=(
                "Optional alert channel, such as EMAIL or SMS. "
                "Must be supplied with --alert-recipient."
            ),
        )
        parser.add_argument(
            "--alert-recipient",
            help=(
                "Optional alert recipient. Must be supplied with "
                "--alert-channel."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Exercise all three data-source pipelines without "
                "permanently saving records, predictions, or alerts."
            ),
        )

    def handle(self, *args, **options):
        observation_date = self._observation_date(
            options.get("observation_date")
        )
        recorded_at = self._recorded_at(
            options.get("recorded_at")
        )
        county_code = options.get("county_code")
        sample_points = options["sample_points"]
        timeout = options["timeout"]
        prediction_batch_size = options[
            "prediction_batch_size"
        ]
        simulation_seed = options.get(
            "simulation_seed"
        )
        alert_channel = options.get(
            "alert_channel"
        )
        alert_recipient = options.get(
            "alert_recipient"
        )
        dry_run = options["dry_run"]

        self._validate_options(
            observation_date=observation_date,
            sample_points=sample_points,
            timeout=timeout,
            prediction_batch_size=prediction_batch_size,
            alert_channel=alert_channel,
            alert_recipient=alert_recipient,
        )

        nasa_end_date = (
            observation_date - timedelta(days=1)
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "1/4 Reconciling NASA POWER data"
            )
        )

        call_command(
            "refresh_nasa_power",
            end_date=nasa_end_date.isoformat(),
            county_code=county_code,
            sample_points=sample_points,
            timeout=timeout,
            prediction_batch_size=(
                prediction_batch_size
            ),
            dry_run=dry_run,
            stdout=self.stdout,
            stderr=self.stderr,
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "2/4 Refreshing Open-Meteo live data"
            )
        )

        call_command(
            "refresh_open_meteo",
            observation_date=(
                observation_date.isoformat()
            ),
            county_code=county_code,
            timeout=timeout,
            dry_run=dry_run,
            stdout=self.stdout,
            stderr=self.stderr,
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "3/4 Generating simulated IoT telemetry"
            )
        )

        call_command(
            "simulate_iot",
            recorded_at=recorded_at.isoformat(),
            county_code=county_code,
            seed=simulation_seed,
            dry_run=dry_run,
            stdout=self.stdout,
            stderr=self.stderr,
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "4/4 Reconciling live High-risk alerts"
            )
        )

        if dry_run:
            self.stdout.write(
                "Alert creation skipped during dry run."
            )
        else:
            try:
                alert_summary = (
                    create_live_high_risk_alerts(
                        observation_date,
                        channel=alert_channel,
                        recipient=alert_recipient,
                    )
                )
            except LiveAlertError as exc:
                raise CommandError(
                    f"Live alert reconciliation failed: {exc}"
                ) from exc

            self.stdout.write(
                "Live alert reconciliation: "
                f"{alert_summary.high_risk_predictions} "
                "eligible High-risk predictions, "
                f"{alert_summary.alerts_created} alerts created, "
                f"{alert_summary.alerts_existing} alerts existing."
            )

        mode = (
            "DRY RUN"
            if dry_run
            else "COMPLETED"
        )

        scope = (
            f"county {county_code}"
            if county_code
            else "all counties"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Live refresh {mode}: "
                f"{scope}, observation date "
                f"{observation_date}, simulated packet time "
                f"{recorded_at.isoformat()}."
            )
        )

    @staticmethod
    def _observation_date(value):
        if value:
            return parse_date(value)

        return timezone.localdate()

    @staticmethod
    def _recorded_at(value):
        if value:
            return parse_recorded_at(value)

        return timezone.now()

    @staticmethod
    def _validate_options(
        *,
        observation_date,
        sample_points,
        timeout,
        prediction_batch_size,
        alert_channel,
        alert_recipient,
    ):
        if observation_date < date(2026, 1, 2):
            raise CommandError(
                "--date must be on or after 2026-01-02 so the "
                "preceding NASA POWER period can be reconciled."
            )

        if observation_date > timezone.localdate():
            raise CommandError(
                "--date cannot be in the future."
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
                "--prediction-batch-size must be greater "
                "than zero."
            )

        if bool(alert_channel) != bool(alert_recipient):
            raise CommandError(
                "--alert-channel and --alert-recipient must "
                "be supplied together."
            )
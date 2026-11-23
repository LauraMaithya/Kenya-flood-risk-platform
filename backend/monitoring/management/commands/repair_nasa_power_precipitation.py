import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from monitoring.models import (
    AlertNotification,
    EnvironmentalObservation,
)
from monitoring.services.prediction_storage import (
    PredictionStorageError,
    refresh_prediction_batch,
)


CORRECTION_FACTOR = Decimal("24")
CORRECTION_MARKER = "|PRECIP_MM_DAY_FIX_V1"
DEFAULT_START = date(2026, 1, 1)
DEFAULT_END = date(2026, 10, 31)


def parse_date(value, option_name):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(
            f"{option_name} must use YYYY-MM-DD format."
        ) from exc


class Command(BaseCommand):
    help = (
        "Repair the one-time x24 precipitation-unit error in existing "
        "2026 NASA POWER observations and recalculate their predictions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            default=DEFAULT_START.isoformat(),
        )
        parser.add_argument(
            "--end-date",
            default=DEFAULT_END.isoformat(),
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Apply the correction. Without this flag, only audit it.",
        )
        parser.add_argument(
            "--backup",
            type=Path,
            help=(
                "CSV path for the pre-correction values. Required with "
                "--confirm."
            ),
        )

    def handle(self, *args, **options):
        start_date = parse_date(options["start_date"], "--start-date")
        end_date = parse_date(options["end_date"], "--end-date")
        if start_date > end_date:
            raise CommandError(
                "--start-date must be on or before --end-date."
            )

        observations = (
            EnvironmentalObservation.objects.filter(
                source=EnvironmentalObservation.Source.NASA_POWER,
                is_synthetic=False,
                observation_date__range=(start_date, end_date),
            )
            .exclude(source_record_id__endswith=CORRECTION_MARKER)
            .select_related("county")
            .order_by("observation_date", "county__name")
        )
        count = observations.count()
        already_corrected = EnvironmentalObservation.objects.filter(
            source=EnvironmentalObservation.Source.NASA_POWER,
            is_synthetic=False,
            observation_date__range=(start_date, end_date),
            source_record_id__endswith=CORRECTION_MARKER,
        ).count()

        if not count:
            self.stdout.write(
                self.style.SUCCESS(
                    "No uncorrected NASA POWER rows remain in the selected "
                    f"period; {already_corrected} rows are already marked."
                )
            )
            return

        old_total = sum(
            observations.values_list("precipitation_max_mm", flat=True),
            Decimal("0"),
        )
        new_total = (old_total / CORRECTION_FACTOR).quantize(
            Decimal("0.001")
        )
        self.stdout.write(
            f"NASA POWER unit audit: {count} rows from {start_date} to "
            f"{end_date}; precipitation total {old_total} mm -> "
            f"{new_total} mm."
        )

        if not options["confirm"]:
            self.stdout.write(
                "Audit only. Add --confirm to repair observations and "
                "recalculate predictions."
            )
            return

        backup_path = options.get("backup")
        if backup_path is None:
            raise CommandError("--backup is required with --confirm.")
        if backup_path.exists():
            raise CommandError(
                f"Backup already exists: {backup_path}. Use a new path."
            )

        alert_count = AlertNotification.objects.filter(
            prediction__observation__in=observations,
            is_test=False,
        ).count()
        if alert_count:
            raise CommandError(
                f"{alert_count} operational alerts refer to affected "
                "predictions. The correction stopped to preserve the alert "
                "audit trail."
            )

        backup_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with backup_path.open("x", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(
                    [
                        "observation_id",
                        "county_code",
                        "county_name",
                        "observation_date",
                        "precipitation_max_mm_before",
                        "source_record_id_before",
                    ]
                )
                for observation in observations.iterator():
                    writer.writerow(
                        [
                            observation.pk,
                            observation.county.code,
                            observation.county.name,
                            observation.observation_date.isoformat(),
                            observation.precipitation_max_mm,
                            observation.source_record_id,
                        ]
                    )
        except OSError as exc:
            raise CommandError(
                f"Could not create correction backup: {exc}"
            ) from exc

        corrected = []
        with transaction.atomic():
            for observation in observations.select_for_update().iterator():
                observation.precipitation_max_mm = (
                    observation.precipitation_max_mm / CORRECTION_FACTOR
                ).quantize(Decimal("0.001"))
                observation.source_record_id = (
                    observation.source_record_id + CORRECTION_MARKER
                )
                observation.updated_at = timezone.now()
                observation.full_clean(
                    validate_unique=False,
                    validate_constraints=False,
                )
                corrected.append(observation)

            EnvironmentalObservation.objects.bulk_update(
                corrected,
                [
                    "precipitation_max_mm",
                    "source_record_id",
                    "updated_at",
                ],
                batch_size=1000,
            )
            try:
                prediction_result = refresh_prediction_batch(
                    corrected,
                    database_batch_size=1000,
                )
            except PredictionStorageError as exc:
                raise CommandError(
                    f"Prediction recalculation failed: {exc}"
                ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Corrected {len(corrected)} NASA POWER observations and "
                f"recalculated {prediction_result.processed} predictions "
                f"({prediction_result.updated} updated, "
                f"{prediction_result.created} created)."
            )
        )
        self.stdout.write(f"Pre-correction backup: {backup_path}")

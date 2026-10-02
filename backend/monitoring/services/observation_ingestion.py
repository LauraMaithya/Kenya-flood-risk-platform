import csv
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from monitoring.models import County, EnvironmentalObservation


REQUIRED_COLUMNS = {
    "county_code",
    "county_name",
    "observation_date",
    "precipitation_max_mm",
    "temperature_mean_c",
    "relative_humidity_mean_pct",
    "soil_wetness_mean_fraction",
    "soil_wetness_max_fraction",
}


class ObservationIngestionError(ValueError):
    """Raised when an observation CSV cannot be safely ingested."""


@dataclass(frozen=True)
class IngestionSummary:
    processed: int
    created: int
    updated: int
    counties_created: int
    dry_run: bool


def _required_value(row, column, row_number):
    value = (row.get(column) or "").strip()
    if not value:
        raise ObservationIngestionError(
            f"Row {row_number}: {column} is required."
        )
    return value


def _parse_decimal(row, column, row_number):
    value = _required_value(row, column, row_number)

    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ObservationIngestionError(
            f"Row {row_number}: {column} must be numeric."
        ) from exc

    if not parsed.is_finite():
        raise ObservationIngestionError(
            f"Row {row_number}: {column} must be finite."
        )

    return parsed


def _parse_date(row, row_number):
    value = _required_value(row, "observation_date", row_number)

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ObservationIngestionError(
            f"Row {row_number}: observation_date must use YYYY-MM-DD."
        ) from exc


def _parse_optional_boolean(row, column, default=False):
    value = (row.get(column) or "").strip().lower()

    if not value:
        return default

    if value in {"true", "1", "yes"}:
        return True

    if value in {"false", "0", "no"}:
        return False

    raise ObservationIngestionError(
        f"{column} must be true or false."
    )


def _optional_decimal(row, column, row_number):
    value = (row.get(column) or "").strip()

    if not value:
        return None

    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ObservationIngestionError(
            f"Row {row_number}: {column} must be numeric."
        ) from exc

    if not parsed.is_finite():
        raise ObservationIngestionError(
            f"Row {row_number}: {column} must be finite."
        )

    return parsed


def _get_or_create_county(row, row_number):
    code = _required_value(row, "county_code", row_number)
    name = _required_value(row, "county_name", row_number)

    try:
        county = County.objects.get(code=code)

        if county.name.casefold() != name.casefold():
            raise ObservationIngestionError(
                f"Row {row_number}: county code {code} already belongs "
                f"to {county.name}, not {name}."
            )

        return county, False
    except County.DoesNotExist:
        county = County(
            code=code,
            name=name,
            slug=slugify(name),
            latitude=_optional_decimal(
                row, "latitude", row_number
            ),
            longitude=_optional_decimal(
                row, "longitude", row_number
            ),
            has_nasa_power_coverage=True,
        )

        try:
            county.full_clean()
            county.save()
        except ValidationError as exc:
            raise ObservationIngestionError(
                f"Row {row_number}: invalid county data: {exc.messages}"
            ) from exc

        return county, True


@transaction.atomic
def ingest_observations(csv_path, dry_run=False):
    path = Path(csv_path)

    if not path.is_file():
        raise ObservationIngestionError(
            f"CSV file does not exist: {path}"
        )

    processed = 0
    created = 0
    updated = 0
    counties_created = 0
    seen_keys = set()

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = REQUIRED_COLUMNS - fieldnames

        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ObservationIngestionError(
                f"Missing required CSV columns: {missing}"
            )

        for row_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue

            observation_date = _parse_date(row, row_number)
            county, county_created = _get_or_create_county(
                row, row_number
            )

            key = (county.pk, observation_date)
            if key in seen_keys:
                raise ObservationIngestionError(
                    f"Row {row_number}: duplicate county and date "
                    f"within the CSV."
                )
            seen_keys.add(key)

            angle = (2 * math.pi * observation_date.month) / 12

            values = {
                "precipitation_max_mm": _parse_decimal(
                    row, "precipitation_max_mm", row_number
                ),
                "temperature_mean_c": _parse_decimal(
                    row, "temperature_mean_c", row_number
                ),
                "relative_humidity_mean_pct": _parse_decimal(
                    row, "relative_humidity_mean_pct", row_number
                ),
                "soil_wetness_mean_fraction": _parse_decimal(
                    row, "soil_wetness_mean_fraction", row_number
                ),
                "soil_wetness_max_fraction": _parse_decimal(
                    row, "soil_wetness_max_fraction", row_number
                ),
                "month_sin": Decimal(f"{math.sin(angle):.8f}"),
                "month_cos": Decimal(f"{math.cos(angle):.8f}"),
                "source_record_id": (
                    (row.get("source_record_id") or "").strip()
                    or f"{county.code}:{observation_date.isoformat()}"
                ),
                "is_synthetic": False,
                "quality_review_required": _parse_optional_boolean(
                    row, "quality_review_required", default=False
                ),
            }

            source = (row.get("source") or "").strip()
            if source:
                values["source"] = source

            observation = EnvironmentalObservation.objects.filter(
                county=county,
                observation_date=observation_date,
            ).first()

            was_created = observation is None

            if was_created:
                observation = EnvironmentalObservation(
                    county=county,
                    observation_date=observation_date,
                )

            for field_name, value in values.items():
                setattr(observation, field_name, value)

            try:
                observation.full_clean()
                observation.save()
            except ValidationError as exc:
                raise ObservationIngestionError(
                    f"Row {row_number}: invalid observation: "
                    f"{exc.messages}"
                ) from exc

            processed += 1
            created += int(was_created)
            updated += int(not was_created)
            counties_created += int(county_created)

    if dry_run:
        transaction.set_rollback(True)

    return IngestionSummary(
        processed=processed,
        created=created,
        updated=updated,
        counties_created=counties_created,
        dry_run=dry_run,
    )
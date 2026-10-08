import csv
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from monitoring.models import (
    County,
    EnvironmentalObservation,
)


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

OBSERVATION_UPDATE_FIELDS = [
    "precipitation_max_mm",
    "temperature_mean_c",
    "relative_humidity_mean_pct",
    "soil_wetness_mean_fraction",
    "soil_wetness_max_fraction",
    "month_sin",
    "month_cos",
    "source",
    "source_record_id",
    "is_synthetic",
    "quality_review_required",
    "updated_at",
]


class ObservationIngestionError(ValueError):
    """Raised when an observation CSV cannot be safely ingested."""


@dataclass(frozen=True)
class IngestionSummary:
    processed: int
    created: int
    updated: int
    counties_created: int
    dry_run: bool
    observation_ids: tuple[int, ...]


def _required_value(row, column, row_number):
    value = (row.get(column) or "").strip()

    if not value:
        raise ObservationIngestionError(
            f"Row {row_number}: {column} is required."
        )

    return value


def _parse_decimal(row, column, row_number):
    value = _required_value(
        row,
        column,
        row_number,
    )

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
    value = _required_value(
        row,
        "observation_date",
        row_number,
    )

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ObservationIngestionError(
            "Row "
            f"{row_number}: observation_date must use "
            "YYYY-MM-DD."
        ) from exc


def _parse_optional_boolean(
    row,
    column,
    row_number,
    default=False,
):
    value = (row.get(column) or "").strip().lower()

    if not value:
        return default

    if value in {"true", "1", "yes"}:
        return True

    if value in {"false", "0", "no"}:
        return False

    raise ObservationIngestionError(
        f"Row {row_number}: {column} must be "
        "true or false."
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


def _county_for_row(
    row,
    row_number,
    county_cache,
):
    code = _required_value(
        row,
        "county_code",
        row_number,
    )
    name = _required_value(
        row,
        "county_name",
        row_number,
    )

    county = county_cache.get(code)

    if county is not None:
        if county.name.casefold() != name.casefold():
            raise ObservationIngestionError(
                f"Row {row_number}: county code {code} "
                f"already belongs to {county.name}, "
                f"not {name}."
            )

        return county, False

    county = County(
        code=code,
        name=name,
        slug=slugify(name),
        latitude=_optional_decimal(
            row,
            "latitude",
            row_number,
        ),
        longitude=_optional_decimal(
            row,
            "longitude",
            row_number,
        ),
        has_nasa_power_coverage=True,
    )

    try:
        county.full_clean()
        county.save()
    except ValidationError as exc:
        raise ObservationIngestionError(
            f"Row {row_number}: invalid county data: "
            f"{exc.messages}"
        ) from exc

    county_cache[code] = county

    return county, True


def _observation_values(
    row,
    row_number,
    observation_date,
    county,
):
    angle = (
        2
        * math.pi
        * (observation_date.month - 1)
    ) / 12

    source = (row.get("source") or "").strip()

    if not source:
        source = (
            EnvironmentalObservation.Source.NASA_POWER
        )

    return {
        "precipitation_max_mm": _parse_decimal(
            row,
            "precipitation_max_mm",
            row_number,
        ),
        "temperature_mean_c": _parse_decimal(
            row,
            "temperature_mean_c",
            row_number,
        ),
        "relative_humidity_mean_pct": _parse_decimal(
            row,
            "relative_humidity_mean_pct",
            row_number,
        ),
        "soil_wetness_mean_fraction": _parse_decimal(
            row,
            "soil_wetness_mean_fraction",
            row_number,
        ),
        "soil_wetness_max_fraction": _parse_decimal(
            row,
            "soil_wetness_max_fraction",
            row_number,
        ),
        "month_sin": Decimal(
            f"{math.sin(angle):.8f}"
        ),
        "month_cos": Decimal(
            f"{math.cos(angle):.8f}"
        ),
        "source": source,
        "source_record_id": (
            (
                row.get("source_record_id")
                or ""
            ).strip()
            or (
                f"{county.code}:"
                f"{observation_date.isoformat()}"
            )
        ),
        "is_synthetic": False,
        "quality_review_required": (
            _parse_optional_boolean(
                row,
                "quality_review_required",
                row_number,
                default=False,
            )
        ),
    }


def _validate_observation(
    observation,
    row_number,
):
    try:
        observation.full_clean(
            validate_unique=False,
            validate_constraints=False,
        )
    except ValidationError as exc:
        raise ObservationIngestionError(
            f"Row {row_number}: invalid observation: "
            f"{exc.messages}"
        ) from exc


@transaction.atomic
def ingest_observations(
    csv_path,
    dry_run=False,
    batch_size=1000,
):
    path = Path(csv_path)

    if not path.is_file():
        raise ObservationIngestionError(
            f"CSV file does not exist: {path}"
        )

    if batch_size <= 0:
        raise ObservationIngestionError(
            "Batch size must be greater than zero."
        )

    county_cache = {
        county.code: county
        for county in County.objects.all()
    }

    existing_observations = {
        (
            observation.county_id,
            observation.observation_date,
        ): observation
        for observation in (
            EnvironmentalObservation.objects.all()
        )
    }

    new_observations = []
    changed_observations = []
    seen_keys = set()
    processed = 0
    counties_created = 0
    validation_rows = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = (
            REQUIRED_COLUMNS - fieldnames
        )

        if missing_columns:
            missing = ", ".join(
                sorted(missing_columns)
            )
            raise ObservationIngestionError(
                "Missing required CSV columns: "
                f"{missing}"
            )

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            if not any(
                (value or "").strip()
                for value in row.values()
            ):
                continue

            observation_date = _parse_date(
                row,
                row_number,
            )
            county, county_created = (
                _county_for_row(
                    row,
                    row_number,
                    county_cache,
                )
            )

            counties_created += int(
                county_created
            )

            key = (
                county.pk,
                observation_date,
            )

            if key in seen_keys:
                raise ObservationIngestionError(
                    f"Row {row_number}: duplicate county "
                    "and date within the CSV."
                )

            seen_keys.add(key)

            values = _observation_values(
                row,
                row_number,
                observation_date,
                county,
            )

            observation = (
                existing_observations.get(key)
            )

            if observation is None:
                observation = (
                    EnvironmentalObservation(
                        county=county,
                        observation_date=(
                            observation_date
                        ),
                    )
                )

                for field_name, value in (
                    values.items()
                ):
                    setattr(
                        observation,
                        field_name,
                        value,
                    )

                new_observations.append(
                    observation
                )
            else:
                for field_name, value in (
                    values.items()
                ):
                    setattr(
                        observation,
                        field_name,
                        value,
                    )

                observation.updated_at = (
                    timezone.now()
                )
                changed_observations.append(
                    observation
                )

            validation_rows.append(
                (
                    observation,
                    row_number,
                )
            )
            processed += 1

    for observation, row_number in validation_rows:
        _validate_observation(
            observation,
            row_number,
        )

    EnvironmentalObservation.objects.bulk_create(
        new_observations,
        batch_size=batch_size,
    )

    if changed_observations:
        EnvironmentalObservation.objects.bulk_update(
            changed_observations,
            OBSERVATION_UPDATE_FIELDS,
            batch_size=batch_size,
        )

    if dry_run:
        transaction.set_rollback(True)

    return IngestionSummary(
        processed=processed,
        created=len(new_observations),
        updated=len(changed_observations),
        counties_created=counties_created,
        dry_run=dry_run,
        observation_ids=tuple(
            observation.pk
            for observation, _row_number
            in validation_rows
        ),
    )
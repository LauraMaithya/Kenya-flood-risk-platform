from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from monitoring.models import (
    EnvironmentalObservation,
)
from monitoring.services.nasa_power_etl import (
    NasaPowerETLError,
)


class NasaPowerStorageError(RuntimeError):
    """Raised when NASA POWER observations cannot be safely stored."""


@dataclass(frozen=True)
class NasaPowerStorageSummary:
    processed: int
    created: int
    updated: int
    unchanged: int
    dry_run: bool


OBSERVATION_FIELDS = (
    "precipitation_max_mm",
    "temperature_mean_c",
    "relative_humidity_mean_pct",
    "soil_wetness_mean_fraction",
    "soil_wetness_max_fraction",
    "month_sin",
    "month_cos",
)


def _observation_values(county, county_day):
    return {
        "precipitation_max_mm": (
            county_day.precipitation_max_mm
        ),
        "temperature_mean_c": (
            county_day.temperature_mean_c
        ),
        "relative_humidity_mean_pct": (
            county_day.relative_humidity_mean_pct
        ),
        "soil_wetness_mean_fraction": (
            county_day.soil_wetness_mean_fraction
        ),
        "soil_wetness_max_fraction": (
            county_day.soil_wetness_max_fraction
        ),
        "month_sin": county_day.month_sin,
        "month_cos": county_day.month_cos,
        "source": (
            EnvironmentalObservation.Source.NASA_POWER
        ),
        "source_record_id": (
            f"NASA_POWER_{county.code}_"
            f"{county_day.observation_date:%Y%m%d}"
        ),
        "is_synthetic": False,
        "quality_review_required": False,
    }


def _values_changed(observation, values):
    fields = (
        *OBSERVATION_FIELDS,
        "source",
        "source_record_id",
        "is_synthetic",
        "quality_review_required",
    )

    return any(
        getattr(observation, field) != values[field]
        for field in fields
    )


@transaction.atomic
def store_nasa_power_county_days(
    county,
    county_days,
    *,
    dry_run=False,
):
    if county.pk is None:
        raise NasaPowerStorageError(
            "The county must be saved before storing observations."
        )

    county_days = tuple(county_days)
    observation_dates = [
        county_day.observation_date
        for county_day in county_days
    ]

    if len(observation_dates) != len(
        set(observation_dates)
    ):
        raise NasaPowerStorageError(
            "NASA POWER county-day input contains duplicate dates."
        )

    created = 0
    updated = 0
    unchanged = 0

    for county_day in county_days:
        values = _observation_values(
            county,
            county_day,
        )
        observation = (
            EnvironmentalObservation.objects
            .filter(
                county=county,
                observation_date=(
                    county_day.observation_date
                ),
            )
            .first()
        )

        if observation is None:
            candidate = EnvironmentalObservation(
                county=county,
                observation_date=(
                    county_day.observation_date
                ),
                **values,
            )

            try:
                candidate.full_clean()
            except ValidationError as exc:
                raise NasaPowerStorageError(
                    "Invalid NASA POWER observation for "
                    f"{county.name} on "
                    f"{county_day.observation_date}: "
                    f"{exc.messages}"
                ) from exc

            if not dry_run:
                candidate.save()

            created += 1
            continue

        if (
            observation.source
            != EnvironmentalObservation.Source.NASA_POWER
        ):
            raise NasaPowerStorageError(
                "NASA POWER cannot overwrite an observation "
                f"from source {observation.source} for "
                f"{county.name} on "
                f"{county_day.observation_date}."
            )

        if not _values_changed(
            observation,
            values,
        ):
            unchanged += 1
            continue

        if observation.predictions.exists():
            raise NasaPowerStorageError(
                "NASA POWER cannot update an observation that "
                "already has stored predictions. Prediction "
                "reconciliation is required first."
            )

        for field, value in values.items():
            setattr(observation, field, value)

        try:
            observation.full_clean()
        except ValidationError as exc:
            raise NasaPowerStorageError(
                "Invalid NASA POWER update for "
                f"{county.name} on "
                f"{county_day.observation_date}: "
                f"{exc.messages}"
            ) from exc

        if not dry_run:
            observation.save(
                update_fields=[
                    *values.keys(),
                    "updated_at",
                ]
            )

        updated += 1

    return NasaPowerStorageSummary(
        processed=len(county_days),
        created=created,
        updated=updated,
        unchanged=unchanged,
        dry_run=dry_run,
    )
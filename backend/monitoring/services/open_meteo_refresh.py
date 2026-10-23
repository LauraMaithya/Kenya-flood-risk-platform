from dataclasses import dataclass

from monitoring.models import (
    EnvironmentalObservation,
)
from monitoring.services.open_meteo import (
    OpenMeteoError,
    fetch_open_meteo_daily_point,
)
from monitoring.services.open_meteo_storage import (
    OpenMeteoStorageError,
    store_open_meteo_daily_point,
)
from monitoring.services.prediction_storage import (
    PredictionStorageError,
    store_prediction,
)


class OpenMeteoRefreshError(RuntimeError):
    """Raised when an Open-Meteo refresh cannot complete safely."""


@dataclass(frozen=True)
class OpenMeteoRefreshSummary:
    county_code: str
    county_name: str
    observation_date: object
    device_created: bool
    reading_created: bool
    reading_updated: bool
    observation_created: bool
    observation_updated: bool
    observation_preserved: bool
    prediction_created: bool
    prediction_existing: bool
    dry_run: bool


def refresh_open_meteo_county(
    county,
    *,
    observation_date,
    timeout=30,
    dry_run=False,
):
    if county.pk is None:
        raise OpenMeteoRefreshError(
            "The county must be saved before refresh."
        )

    if county.latitude is None or county.longitude is None:
        raise OpenMeteoRefreshError(
            f"{county.name} does not have coordinates."
        )

    try:
        daily_point = fetch_open_meteo_daily_point(
            latitude=county.latitude,
            longitude=county.longitude,
            observation_date=observation_date,
            timeout=timeout,
        )
    except OpenMeteoError as exc:
        raise OpenMeteoRefreshError(
            f"Open-Meteo extraction failed for "
            f"{county.name}: {exc}"
        ) from exc

    try:
        storage = store_open_meteo_daily_point(
            county,
            daily_point,
            dry_run=dry_run,
        )
    except OpenMeteoStorageError as exc:
        raise OpenMeteoRefreshError(
            f"Open-Meteo storage failed for "
            f"{county.name}: {exc}"
        ) from exc

    prediction_created = False
    prediction_existing = False

    if not dry_run:
        observation = (
            EnvironmentalObservation.objects.filter(
                county=county,
                observation_date=observation_date,
                source=(
                    EnvironmentalObservation.Source.LIVE_API_IOT
                ),
                is_synthetic=False,
            ).first()
        )

        if observation is not None:
            try:
                prediction = store_prediction(
                    observation
                )
            except PredictionStorageError as exc:
                raise OpenMeteoRefreshError(
                    "Open-Meteo prediction failed for "
                    f"{county.name}: {exc}"
                ) from exc

            prediction_created = prediction.created
            prediction_existing = not prediction.created

    return OpenMeteoRefreshSummary(
        county_code=county.code,
        county_name=county.name,
        observation_date=observation_date,
        device_created=storage.device_created,
        reading_created=storage.reading_created,
        reading_updated=storage.reading_updated,
        observation_created=storage.observation_created,
        observation_updated=storage.observation_updated,
        observation_preserved=(
            storage.observation_preserved
        ),
        prediction_created=prediction_created,
        prediction_existing=prediction_existing,
        dry_run=dry_run,
    )
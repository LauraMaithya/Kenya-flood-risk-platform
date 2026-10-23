from dataclasses import dataclass
from itertools import islice

from monitoring.models import (
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.prediction_service import (
    PredictionServiceError,
    get_model_release,
)
from monitoring.services.prediction_storage import (
    PredictionStorageError,
    store_prediction_batch,
)


class NasaPowerPredictionError(RuntimeError):
    """Raised when NASA observations cannot be predicted safely."""


@dataclass(frozen=True)
class NasaPowerPredictionSummary:
    observations_found: int
    predictions_pending: int
    predictions_created: int
    predictions_existing: int
    batches_processed: int


def _chunks(iterator, batch_size):
    while True:
        batch = list(islice(iterator, batch_size))

        if not batch:
            return

        yield batch


def predict_missing_nasa_power(
    counties,
    *,
    start_date,
    end_date,
    batch_size=1000,
):
    county_rows = list(counties)

    if not county_rows:
        raise NasaPowerPredictionError(
            "At least one county is required for prediction."
        )

    if start_date > end_date:
        raise NasaPowerPredictionError(
            "Prediction start date must be on or before end date."
        )

    if batch_size <= 0:
        raise NasaPowerPredictionError(
            "Prediction batch size must be greater than zero."
        )

    county_ids = []

    for county in county_rows:
        if county.pk is None:
            raise NasaPowerPredictionError(
                "Every county must be saved before prediction."
            )

        if county.pk not in county_ids:
            county_ids.append(county.pk)

    observations = (
        EnvironmentalObservation.objects.filter(
            county_id__in=county_ids,
            observation_date__range=(
                start_date,
                end_date,
            ),
            source=(
                EnvironmentalObservation.Source.NASA_POWER
            ),
            is_synthetic=False,
        )
        .order_by(
            "observation_date",
            "county_id",
        )
    )

    observations_found = observations.count()

    try:
        release = get_model_release()
    except PredictionServiceError as exc:
        raise NasaPowerPredictionError(str(exc)) from exc

    existing_observation_ids = (
        FloodPrediction.objects.filter(
            model_release_id=release.release_id,
            observation__in=observations,
        ).values_list(
            "observation_id",
            flat=True,
        )
    )

    pending = observations.exclude(
        pk__in=existing_observation_ids
    )

    predictions_pending = pending.count()
    predictions_created = 0
    predictions_existing = 0
    batches_processed = 0

    iterator = pending.iterator(
        chunk_size=batch_size
    )

    for observation_batch in _chunks(
        iterator,
        batch_size,
    ):
        try:
            result = store_prediction_batch(
                observation_batch,
                database_batch_size=batch_size,
            )
        except PredictionStorageError as exc:
            first_id = observation_batch[0].pk
            last_id = observation_batch[-1].pk

            raise NasaPowerPredictionError(
                "NASA prediction batch failed for "
                f"observation IDs {first_id}-{last_id}: {exc}"
            ) from exc

        batches_processed += 1
        predictions_created += result.created
        predictions_existing += (
            result.skipped_existing
        )

    predictions_existing += (
        observations_found - predictions_pending
    )

    return NasaPowerPredictionSummary(
        observations_found=observations_found,
        predictions_pending=predictions_pending,
        predictions_created=predictions_created,
        predictions_existing=predictions_existing,
        batches_processed=batches_processed,
    )
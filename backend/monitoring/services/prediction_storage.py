from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from monitoring.models import FloodPrediction
from monitoring.services.prediction_service import (
    PredictionServiceError,
    get_model_release,
    predict_observation,
    predict_observations,
)


class PredictionStorageError(RuntimeError):
    """Raised when a model result cannot be safely stored."""


@dataclass(frozen=True)
class StoredPrediction:
    prediction: FloodPrediction
    created: bool


@dataclass(frozen=True)
class BatchStorageResult:
    processed: int
    created: int
    skipped_existing: int


def _decimal_for_field(field_name, value):
    field = FloodPrediction._meta.get_field(field_name)
    decimal_value = Decimal(str(value))

    if getattr(field, "decimal_places", None) is not None:
        quantum = Decimal(1).scaleb(-field.decimal_places)
        decimal_value = decimal_value.quantize(quantum)

    return decimal_value


def _prediction_values(result):
    return {
        "risk_level": result.risk_level,
        "probability_low": _decimal_for_field(
            "probability_low",
            result.probability_low,
        ),
        "probability_medium": _decimal_for_field(
            "probability_medium",
            result.probability_medium,
        ),
        "probability_high": _decimal_for_field(
            "probability_high",
            result.probability_high,
        ),
        "decision_rule": (
            f"HIGH_THRESHOLD_{result.high_threshold:.2f}"
        ),
        "high_probability_threshold": _decimal_for_field(
            "high_probability_threshold",
            result.high_threshold,
        ),
    }


def _validate_observation(observation):
    if observation.pk is None:
        raise PredictionStorageError(
            "The observation must be saved before prediction."
        )

    if observation.is_synthetic:
        raise PredictionStorageError(
            "Synthetic observations cannot receive "
            "production predictions."
        )


@transaction.atomic
def store_prediction(observation):
    _validate_observation(observation)

    try:
        result = predict_observation(observation)
    except PredictionServiceError as exc:
        raise PredictionStorageError(str(exc)) from exc

    prediction, created = (
        FloodPrediction.objects.update_or_create(
            observation=observation,
            model_release_id=result.model_release_id,
            defaults=_prediction_values(result),
        )
    )

    try:
        prediction.full_clean()
    except ValidationError as exc:
        raise PredictionStorageError(
            f"Invalid stored prediction: {exc.messages}"
        ) from exc

    return StoredPrediction(
        prediction=prediction,
        created=created,
    )


@transaction.atomic
def store_prediction_batch(
    observations,
    *,
    database_batch_size=1000,
):
    observation_rows = list(observations)

    if database_batch_size <= 0:
        raise PredictionStorageError(
            "Database batch size must be greater than zero."
        )

    if not observation_rows:
        return BatchStorageResult(
            processed=0,
            created=0,
            skipped_existing=0,
        )

    for observation in observation_rows:
        _validate_observation(observation)

    observation_ids = [
        observation.pk
        for observation in observation_rows
    ]

    if len(observation_ids) != len(set(observation_ids)):
        raise PredictionStorageError(
            "The batch contains duplicate observations."
        )

    release = get_model_release()

    existing_observation_ids = set(
        FloodPrediction.objects.filter(
            observation_id__in=observation_ids,
            model_release_id=release.release_id,
        ).values_list(
            "observation_id",
            flat=True,
        )
    )

    pending_observations = [
        observation
        for observation in observation_rows
        if observation.pk not in existing_observation_ids
    ]

    try:
        results = predict_observations(
            pending_observations
        )
    except PredictionServiceError as exc:
        raise PredictionStorageError(str(exc)) from exc

    predictions = []

    for observation, result in zip(
        pending_observations,
        results,
        strict=True,
    ):
        if result.model_release_id != release.release_id:
            raise PredictionStorageError(
                "The batch prediction release does not match "
                "the loaded model release."
            )

        prediction = FloodPrediction(
            observation=observation,
            model_release_id=result.model_release_id,
            **_prediction_values(result),
        )

        try:
            prediction.full_clean(
                validate_unique=False,
                validate_constraints=False,
            )
        except ValidationError as exc:
            raise PredictionStorageError(
                "Invalid prediction for observation "
                f"{observation.pk}: {exc.messages}"
            ) from exc

        predictions.append(prediction)

    FloodPrediction.objects.bulk_create(
        predictions,
        batch_size=database_batch_size,
    )

    return BatchStorageResult(
        processed=len(observation_rows),
        created=len(predictions),
        skipped_existing=len(existing_observation_ids),
    )
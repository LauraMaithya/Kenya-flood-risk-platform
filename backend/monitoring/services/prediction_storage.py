from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from monitoring.models import FloodPrediction
from monitoring.services.prediction_service import (
    PredictionServiceError,
    predict_observation,
)


class PredictionStorageError(RuntimeError):
    """Raised when a model result cannot be safely stored."""


@dataclass(frozen=True)
class StoredPrediction:
    prediction: FloodPrediction
    created: bool


def _decimal_for_field(field_name, value):
    field = FloodPrediction._meta.get_field(field_name)
    decimal_value = Decimal(str(value))

    if getattr(field, "decimal_places", None) is not None:
        quantum = Decimal(1).scaleb(-field.decimal_places)
        decimal_value = decimal_value.quantize(quantum)

    return decimal_value


@transaction.atomic
def store_prediction(observation):
    if observation.pk is None:
        raise PredictionStorageError(
            "The observation must be saved before prediction."
        )

    if observation.is_synthetic:
        raise PredictionStorageError(
            "Synthetic observations cannot receive "
            "production predictions."
        )

    try:
        result = predict_observation(observation)
    except PredictionServiceError as exc:
        raise PredictionStorageError(str(exc)) from exc

    decision_rule = (
        f"HIGH_THRESHOLD_{result.high_threshold:.2f}"
    )

    defaults = {
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
        "decision_rule": decision_rule,
        "high_probability_threshold": _decimal_for_field(
            "high_probability_threshold",
            result.high_threshold,
        ),
    }

    prediction, created = (
        FloodPrediction.objects.update_or_create(
            observation=observation,
            model_release_id=result.model_release_id,
            defaults=defaults,
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
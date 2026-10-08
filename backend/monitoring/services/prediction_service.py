import csv
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

import joblib
import pandas as pd
from django.conf import settings


class PredictionServiceError(RuntimeError):
    """Raised when the locked model cannot safely make a prediction."""


@dataclass(frozen=True)
class ModelRelease:
    model: object
    release_id: str
    version: str
    feature_names: tuple
    class_order: tuple
    model_class_order: tuple
    high_threshold: float
    fallback_classes: tuple
    checksum: str


@dataclass(frozen=True)
class PredictionResult:
    risk_level: str
    probability_low: float
    probability_medium: float
    probability_high: float
    model_release_id: str
    model_version: str
    high_threshold: float


def _calculate_sha256(path):
    digest = hashlib.sha256()

    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _read_schema_features():
    with settings.MODEL_SCHEMA_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as schema_file:
        rows = list(csv.DictReader(schema_file))

    rows.sort(key=lambda row: int(row["feature_position"]))
    return tuple(row["feature"] for row in rows)


@lru_cache(maxsize=1)
def get_model_release():
    required_paths = (
        settings.MODEL_BUNDLE_PATH,
        settings.MODEL_METADATA_PATH,
        settings.MODEL_SCHEMA_PATH,
    )

    for path in required_paths:
        if not path.is_file():
            raise PredictionServiceError(
                f"Required model artifact is missing: {path}"
            )

    with settings.MODEL_METADATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as metadata_file:
        metadata = json.load(metadata_file)

    expected_checksum = metadata["bundle_sha256"].lower()
    actual_checksum = _calculate_sha256(
        settings.MODEL_BUNDLE_PATH
    ).lower()

    if actual_checksum != expected_checksum:
        raise PredictionServiceError(
            "The model bundle checksum does not match its metadata."
        )

    bundle = joblib.load(settings.MODEL_BUNDLE_PATH)

    required_keys = {
        "model",
        "model_release_id",
        "model_version",
        "feature_names",
        "class_order",
        "model_class_order",
        "decision_rule",
    }

    missing_keys = required_keys - set(bundle)
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise PredictionServiceError(
            f"Model bundle is missing required keys: {missing}"
        )

    feature_names = tuple(bundle["feature_names"])
    metadata_features = tuple(metadata["feature_names"])
    schema_features = _read_schema_features()

    if not (
        feature_names == metadata_features == schema_features
    ):
        raise PredictionServiceError(
            "Feature order differs between the bundle, metadata "
            "and input schema."
        )

    release_id = bundle["model_release_id"]
    version = bundle["model_version"]

    if release_id != metadata["model_release_id"]:
        raise PredictionServiceError(
            "Model release ID differs between bundle and metadata."
        )

    if version != metadata["model_version"]:
        raise PredictionServiceError(
            "Model version differs between bundle and metadata."
        )

    class_order = tuple(bundle["class_order"])
    model_class_order = tuple(bundle["model_class_order"])

    if class_order != tuple(metadata["class_order"]):
        raise PredictionServiceError(
            "Public class order differs between bundle and metadata."
        )

    if model_class_order != tuple(metadata["model_class_order"]):
        raise PredictionServiceError(
            "Model probability order differs between artifacts."
        )

    model = bundle["model"]

    if len(model.classes_) != len(model_class_order):
        raise PredictionServiceError(
            "Estimator probability columns do not match the "
            "saved model class order."
        )

    decision_rule = bundle["decision_rule"]
    metadata_rule = metadata["decision_rule"]

    high_threshold = float(
        decision_rule["high_probability_threshold"]
    )
    fallback_classes = tuple(
        decision_rule["fallback_classes"]
    )

    if not math.isclose(
        high_threshold,
        float(metadata_rule["high_probability_threshold"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise PredictionServiceError(
            "High-risk threshold differs between artifacts."
        )

    if fallback_classes != tuple(
        metadata_rule["fallback_classes"]
    ):
        raise PredictionServiceError(
            "Fallback classes differ between artifacts."
        )

    return ModelRelease(
        model=model,
        release_id=release_id,
        version=version,
        feature_names=feature_names,
        class_order=class_order,
        model_class_order=model_class_order,
        high_threshold=high_threshold,
        fallback_classes=fallback_classes,
        checksum=actual_checksum,
    )


def clear_model_cache():
    get_model_release.cache_clear()


def _validated_feature_values(
    features: Mapping,
    feature_names,
    *,
    row_number=None,
):
    missing_features = [
        feature
        for feature in feature_names
        if feature not in features
    ]

    row_prefix = (
        f"Row {row_number}: "
        if row_number is not None
        else ""
    )

    if missing_features:
        missing = ", ".join(missing_features)
        raise PredictionServiceError(
            f"{row_prefix}Missing prediction features: {missing}"
        )

    feature_values = []

    for feature_name in feature_names:
        try:
            value = float(features[feature_name])
        except (TypeError, ValueError) as exc:
            raise PredictionServiceError(
                f"{row_prefix}{feature_name} must be numeric."
            ) from exc

        if not math.isfinite(value):
            raise PredictionServiceError(
                f"{row_prefix}{feature_name} must be finite."
            )

        feature_values.append(value)

    return feature_values


def _prediction_result(release, raw_probabilities):
    probabilities = {
        class_name: float(probability)
        for class_name, probability in zip(
            release.model_class_order,
            raw_probabilities,
            strict=True,
        )
    }

    if not math.isclose(
        sum(probabilities.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-10,
    ):
        raise PredictionServiceError(
            "Model probabilities do not sum to one."
        )

    if probabilities["High"] >= release.high_threshold:
        risk_level = "High"
    else:
        risk_level = max(
            release.fallback_classes,
            key=probabilities.__getitem__,
        )

    return PredictionResult(
        risk_level=risk_level,
        probability_low=probabilities["Low"],
        probability_medium=probabilities["Medium"],
        probability_high=probabilities["High"],
        model_release_id=release.release_id,
        model_version=release.version,
        high_threshold=release.high_threshold,
    )


def predict_feature_rows(feature_rows):
    release = get_model_release()
    rows = list(feature_rows)

    if not rows:
        return tuple()

    validated_rows = [
        _validated_feature_values(
            features,
            release.feature_names,
            row_number=index,
        )
        for index, features in enumerate(
            rows,
            start=1,
        )
    ]

    prediction_frame = pd.DataFrame(
        validated_rows,
        columns=release.feature_names,
    )

    probability_matrix = release.model.predict_proba(
        prediction_frame
    )

    if len(probability_matrix) != len(rows):
        raise PredictionServiceError(
            "The model returned an unexpected number "
            "of probability rows."
        )

    return tuple(
        _prediction_result(
            release,
            raw_probabilities,
        )
        for raw_probabilities in probability_matrix
    )


def predict_features(features: Mapping):
    return predict_feature_rows([features])[0]


def predict_observations(observations):
    observation_rows = list(observations)

    for observation in observation_rows:
        if observation.is_synthetic:
            raise PredictionServiceError(
                "Synthetic observations cannot receive "
                "production predictions."
            )

    release = get_model_release()

    feature_rows = [
        {
            feature_name: getattr(
                observation,
                feature_name,
            )
            for feature_name in release.feature_names
        }
        for observation in observation_rows
    ]

    return predict_feature_rows(feature_rows)


def predict_observation(observation):
    return predict_observations([observation])[0]
from dataclasses import dataclass

from django.db import transaction

from monitoring.models import (
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.alert_service import (
    AlertServiceError,
    create_high_risk_alert,
)
from monitoring.services.observation_ingestion import (
    ObservationIngestionError,
    ingest_observations,
)
from monitoring.services.prediction_service import (
    get_model_release,
)
from monitoring.services.prediction_storage import (
    PredictionStorageError,
    store_prediction_batch,
)


class DailyRefreshError(RuntimeError):
    """Raised when the daily refresh cannot complete safely."""


@dataclass(frozen=True)
class DailyRefreshSummary:
    observations_processed: int
    observations_created: int
    observations_updated: int
    predictions_created: int
    predictions_existing: int
    high_risk_predictions: int
    alerts_created: int
    alerts_existing: int
    dry_run: bool


def _validate_alert_options(channel, recipient):
    if bool(channel) != bool(recipient):
        raise DailyRefreshError(
            "Alert channel and recipient must be "
            "provided together."
        )


@transaction.atomic
def run_daily_refresh(
    csv_path,
    *,
    batch_size=1000,
    dry_run=False,
    alert_channel=None,
    alert_recipient=None,
):
    _validate_alert_options(
        alert_channel,
        alert_recipient,
    )

    try:
        ingestion = ingest_observations(
            csv_path,
            dry_run=dry_run,
            batch_size=batch_size,
        )
    except ObservationIngestionError as exc:
        raise DailyRefreshError(str(exc)) from exc

    if dry_run or not ingestion.observation_ids:
        return DailyRefreshSummary(
            observations_processed=(
                ingestion.processed
            ),
            observations_created=ingestion.created,
            observations_updated=ingestion.updated,
            predictions_created=0,
            predictions_existing=0,
            high_risk_predictions=0,
            alerts_created=0,
            alerts_existing=0,
            dry_run=dry_run,
        )

    observations = list(
        EnvironmentalObservation.objects.filter(
            pk__in=ingestion.observation_ids,
            is_synthetic=False,
        ).order_by(
            "observation_date",
            "county_id",
        )
    )

    if len(observations) != len(
        ingestion.observation_ids
    ):
        raise DailyRefreshError(
            "Not all imported observations were found "
            "after ingestion."
        )

    try:
        prediction_result = store_prediction_batch(
            observations,
            database_batch_size=batch_size,
        )
    except PredictionStorageError as exc:
        raise DailyRefreshError(str(exc)) from exc

    release = get_model_release()

    high_predictions = list(
        FloodPrediction.objects.select_related(
            "observation__county"
        )
        .filter(
            observation_id__in=ingestion.observation_ids,
            model_release_id=release.release_id,
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )
        .order_by(
            "observation__observation_date",
            "observation__county_id",
        )
    )

    alerts_created = 0
    alerts_existing = 0

    if alert_channel and alert_recipient:
        for prediction in high_predictions:
            try:
                alert_result = create_high_risk_alert(
                    prediction,
                    channel=alert_channel,
                    recipient=alert_recipient,
                )
            except AlertServiceError as exc:
                raise DailyRefreshError(
                    "Alert creation failed for prediction "
                    f"{prediction.pk}: {exc}"
                ) from exc

            alerts_created += int(
                alert_result.created
            )
            alerts_existing += int(
                not alert_result.created
            )

    return DailyRefreshSummary(
        observations_processed=ingestion.processed,
        observations_created=ingestion.created,
        observations_updated=ingestion.updated,
        predictions_created=(
            prediction_result.created
        ),
        predictions_existing=(
            prediction_result.skipped_existing
        ),
        high_risk_predictions=len(
            high_predictions
        ),
        alerts_created=alerts_created,
        alerts_existing=alerts_existing,
        dry_run=False,
    )
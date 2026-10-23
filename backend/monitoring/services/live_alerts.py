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


class LiveAlertError(RuntimeError):
    """Raised when current live alerts cannot be created safely."""


@dataclass(frozen=True)
class LiveAlertSummary:
    observation_date: object
    high_risk_predictions: int
    alerts_created: int
    alerts_existing: int


def _validate_alert_options(
    channel,
    recipient,
):
    if (channel is None) != (recipient is None):
        raise LiveAlertError(
            "Alert channel and recipient must be provided together."
        )


@transaction.atomic
def create_live_high_risk_alerts(
    observation_date,
    *,
    channel=None,
    recipient=None,
):
    _validate_alert_options(
        channel,
        recipient,
    )

    predictions = list(
        FloodPrediction.objects.select_related(
            "observation__county"
        )
        .filter(
            observation__observation_date=observation_date,
            observation__source=(
                EnvironmentalObservation.Source.LIVE_API_IOT
            ),
            observation__is_synthetic=False,
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )
        .order_by(
            "observation__county_id"
        )
    )

    alerts_created = 0
    alerts_existing = 0

    if channel is not None:
        for prediction in predictions:
            try:
                result = create_high_risk_alert(
                    prediction,
                    channel=channel,
                    recipient=recipient,
                )
            except AlertServiceError as exc:
                raise LiveAlertError(
                    "Live alert creation failed for "
                    f"prediction {prediction.pk}: {exc}"
                ) from exc

            alerts_created += int(
                result.created
            )
            alerts_existing += int(
                not result.created
            )

    return LiveAlertSummary(
        observation_date=observation_date,
        high_risk_predictions=len(
            predictions
        ),
        alerts_created=alerts_created,
        alerts_existing=alerts_existing,
    )
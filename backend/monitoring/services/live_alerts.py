from dataclasses import dataclass

from django.conf import settings

from monitoring.models import (
    AlertNotification,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.alert_service import (
    AlertServiceError,
    create_high_risk_alert,
    deliver_email_alert,
)


class LiveAlertError(RuntimeError):
    """Raised when current live alerts cannot be created safely."""


@dataclass(frozen=True)
class LiveAlertSummary:
    observation_date: object
    high_risk_predictions: int
    alerts_created: int
    alerts_existing: int
    emails_sent: int
    emails_failed: int


def create_live_high_risk_alerts(
    observation_date,
    *,
    email_recipients=None,
):
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
    emails_sent = 0
    emails_failed = 0
    recipients = (
        settings.ALERT_EMAIL_RECIPIENTS
        if email_recipients is None
        else email_recipients
    )
    recipients = list(dict.fromkeys(recipients))

    for prediction in predictions:
        try:
            result = create_high_risk_alert(
                prediction,
                channel=AlertNotification.Channel.IN_APP,
                recipient=settings.IN_APP_ALERT_RECIPIENT,
            )
        except AlertServiceError as exc:
            raise LiveAlertError(
                "Live in-app alert creation failed for "
                f"prediction {prediction.pk}: {exc}"
            ) from exc

        alerts_created += int(result.created)
        alerts_existing += int(not result.created)

        for recipient in recipients:
            try:
                result = create_high_risk_alert(
                    prediction,
                    channel=AlertNotification.Channel.EMAIL,
                    recipient=recipient,
                )
            except AlertServiceError as exc:
                raise LiveAlertError(
                    "Live email alert creation failed for "
                    f"prediction {prediction.pk}: {exc}"
                ) from exc

            alerts_created += int(
                result.created
            )
            alerts_existing += int(
                not result.created
            )

            delivered = deliver_email_alert(result.alert)
            emails_sent += int(
                delivered.status == AlertNotification.Status.SENT
            )
            emails_failed += int(
                delivered.status == AlertNotification.Status.FAILED
            )

    return LiveAlertSummary(
        observation_date=observation_date,
        high_risk_predictions=len(
            predictions
        ),
        alerts_created=alerts_created,
        alerts_existing=alerts_existing,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
    )

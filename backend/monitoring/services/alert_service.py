from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from monitoring.models import AlertNotification


class AlertServiceError(RuntimeError):
    """Raised when an alert cannot be safely created or updated."""


@dataclass(frozen=True)
class AlertCreation:
    alert: AlertNotification
    created: bool


def _validate_channel_and_recipient(channel, recipient):
    valid_channels = dict(
        AlertNotification._meta.get_field("channel").choices
    )

    if channel not in valid_channels:
        raise AlertServiceError(
            f"Unsupported alert channel: {channel}"
        )

    recipient = recipient.strip()

    if not recipient:
        raise AlertServiceError("An alert recipient is required.")

    if channel == "EMAIL":
        try:
            validate_email(recipient)
        except ValidationError as exc:
            raise AlertServiceError(
                "A valid email recipient is required."
            ) from exc

    return recipient


def _build_alert_message(prediction):
    observation = prediction.observation
    probability = float(prediction.probability_high) * 100

    return (
        f"High flood risk detected for "
        f"{observation.county.name} on "
        f"{observation.observation_date:%Y-%m-%d}. "
        f"High-risk probability: {probability:.1f}%."
    )


@transaction.atomic
def create_high_risk_alert(
    prediction,
    *,
    channel,
    recipient,
):
    if prediction.pk is None:
        raise AlertServiceError(
            "The prediction must be saved before alert creation."
        )

    if prediction.risk_level != "High":
        raise AlertServiceError(
            "Alerts are created only for High-risk predictions."
        )

    recipient = _validate_channel_and_recipient(
        channel,
        recipient,
    )
    message = _build_alert_message(prediction)

    alert, created = AlertNotification.objects.get_or_create(
        prediction=prediction,
        channel=channel,
        recipient=recipient,
        defaults={
            "message": message,
            "status": "PENDING",
            "failure_reason": "",
            "sent_at": None,
        },
    )

    if not created and alert.status == "PENDING":
        if alert.message != message:
            alert.message = message
            alert.full_clean()
            alert.save(update_fields=["message"])

    try:
        alert.full_clean()
    except ValidationError as exc:
        raise AlertServiceError(
            f"Invalid alert: {exc.messages}"
        ) from exc

    return AlertCreation(alert=alert, created=created)


@transaction.atomic
def mark_alert_sent(alert):
    locked_alert = AlertNotification.objects.select_for_update().get(
        pk=alert.pk
    )
    locked_alert.status = "SENT"
    locked_alert.failure_reason = ""
    locked_alert.sent_at = timezone.now()

    try:
        locked_alert.full_clean()
        locked_alert.save(
            update_fields=[
                "status",
                "failure_reason",
                "sent_at",
            ]
        )
    except ValidationError as exc:
        raise AlertServiceError(
            f"Invalid sent-alert state: {exc.messages}"
        ) from exc

    return locked_alert


@transaction.atomic
def mark_alert_failed(alert, failure_reason):
    failure_reason = failure_reason.strip()

    if not failure_reason:
        raise AlertServiceError(
            "A failure reason is required."
        )

    locked_alert = AlertNotification.objects.select_for_update().get(
        pk=alert.pk
    )
    locked_alert.status = "FAILED"
    locked_alert.failure_reason = failure_reason
    locked_alert.sent_at = None

    try:
        locked_alert.full_clean()
        locked_alert.save(
            update_fields=[
                "status",
                "failure_reason",
                "sent_at",
            ]
        )
    except ValidationError as exc:
        raise AlertServiceError(
            f"Invalid failed-alert state: {exc.messages}"
        ) from exc

    return locked_alert
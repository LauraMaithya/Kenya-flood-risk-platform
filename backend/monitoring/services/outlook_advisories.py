from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from monitoring.models import (
    AlertNotification,
    County,
    MonthlyOutlookAdvisory,
)


class OutlookAdvisoryError(RuntimeError):
    """Raised when an accepted outlook cannot be advised safely."""


@dataclass(frozen=True)
class OutlookAdvisorySummary:
    qualifying_county_months: int
    advisories_created: int
    advisories_existing: int
    emails_sent: int
    emails_failed: int


def _target_date(value):
    try:
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1)
    except (AttributeError, TypeError, ValueError) as exc:
        raise OutlookAdvisoryError(
            f"Invalid outlook target month: {value!r}."
        ) from exc


def _message(county, target_month, issued_on, probability):
    return (
        f"Monthly flood outlook advisory for {county.name}, "
        f"{target_month:%B %Y}. Estimated flood likelihood: "
        f"{float(probability) * 100:.1f}%. Issued {issued_on:%Y-%m-%d}. "
        "Review preparedness plans. This is an advance planning "
        "advisory, not a live flood warning."
    )


def _should_notify(county, target_month, issued_on, probability):
    previous = (
        MonthlyOutlookAdvisory.objects.filter(
            county=county,
            target_month=target_month,
            issued_on__lt=issued_on,
            channel=AlertNotification.Channel.IN_APP,
        )
        .order_by("-issued_on", "-pk")
        .first()
    )
    if previous is None:
        return True
    change_threshold = Decimal(
        str(settings.OUTLOOK_ADVISORY_CHANGE_THRESHOLD)
    )
    return probability - previous.probability_high >= change_threshold


@transaction.atomic
def _create_advisory(
    *, county, target_month, issued_on, probability, channel, recipient
):
    sent_at = (
        timezone.now()
        if channel == AlertNotification.Channel.IN_APP
        else None
    )
    return MonthlyOutlookAdvisory.objects.get_or_create(
        county=county,
        target_month=target_month,
        issued_on=issued_on,
        channel=channel,
        recipient=recipient,
        defaults={
            "probability_high": probability,
            "message": _message(
                county, target_month, issued_on, probability
            ),
            "status": (
                AlertNotification.Status.SENT
                if channel == AlertNotification.Channel.IN_APP
                else AlertNotification.Status.PENDING
            ),
            "sent_at": sent_at,
        },
    )


def _deliver_email(advisory):
    if advisory.status == AlertNotification.Status.SENT:
        return advisory
    try:
        delivered = send_mail(
            subject=(
                "Kenya Flood Risk Outlook: "
                f"{advisory.county.name} · "
                f"{advisory.target_month:%B %Y}"
            ),
            message=advisory.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[advisory.recipient],
            fail_silently=False,
        )
    except Exception as exc:
        advisory.status = AlertNotification.Status.FAILED
        advisory.failure_reason = str(exc).strip() or exc.__class__.__name__
        advisory.sent_at = None
    else:
        if delivered == 1:
            advisory.status = AlertNotification.Status.SENT
            advisory.failure_reason = ""
            advisory.sent_at = timezone.now()
        else:
            advisory.status = AlertNotification.Status.FAILED
            advisory.failure_reason = (
                "The email backend did not confirm delivery."
            )
            advisory.sent_at = None
    advisory.full_clean()
    advisory.save(
        update_fields=["status", "failure_reason", "sent_at"]
    )
    return advisory


def create_outlook_advisories(*, scores, issued_on):
    if not isinstance(issued_on, date):
        raise OutlookAdvisoryError("A valid outlook issue date is required.")
    threshold = Decimal(str(settings.OUTLOOK_ADVISORY_THRESHOLD))
    counties = {
        county.name: county
        for county in County.objects.filter(
            name__in={name for estimates in scores.values() for name in estimates}
        )
    }
    recipients = list(dict.fromkeys(settings.ALERT_EMAIL_RECIPIENTS))
    qualifying = created = existing = sent = failed = 0

    for target_key, estimates in sorted(scores.items()):
        target_month = _target_date(target_key)
        for county_name, raw_probability in sorted(estimates.items()):
            probability = Decimal(str(raw_probability)).quantize(
                Decimal("0.000001")
            )
            if probability < threshold:
                continue
            county = counties.get(county_name)
            if county is None:
                raise OutlookAdvisoryError(
                    f"Outlook county was not found: {county_name}."
                )
            qualifying += 1
            if not _should_notify(
                county, target_month, issued_on, probability
            ):
                continue
            advisory, was_created = _create_advisory(
                county=county,
                target_month=target_month,
                issued_on=issued_on,
                probability=probability,
                channel=AlertNotification.Channel.IN_APP,
                recipient=settings.IN_APP_ALERT_RECIPIENT,
            )
            created += int(was_created)
            existing += int(not was_created)
            for recipient in recipients:
                advisory, was_created = _create_advisory(
                    county=county,
                    target_month=target_month,
                    issued_on=issued_on,
                    probability=probability,
                    channel=AlertNotification.Channel.EMAIL,
                    recipient=recipient,
                )
                created += int(was_created)
                existing += int(not was_created)
                delivered = _deliver_email(advisory)
                sent += int(
                    delivered.status == AlertNotification.Status.SENT
                )
                failed += int(
                    delivered.status == AlertNotification.Status.FAILED
                )

    return OutlookAdvisorySummary(
        qualifying_county_months=qualifying,
        advisories_created=created,
        advisories_existing=existing,
        emails_sent=sent,
        emails_failed=failed,
    )


@transaction.atomic
def acknowledge_outlook_advisory(advisory, user):
    if advisory.channel != AlertNotification.Channel.IN_APP:
        raise OutlookAdvisoryError(
            "Only in-app outlook advisories can be acknowledged."
        )
    if not getattr(user, "is_authenticated", False) or user.pk is None:
        raise OutlookAdvisoryError("An authenticated user is required.")
    locked = MonthlyOutlookAdvisory.objects.select_for_update().get(
        pk=advisory.pk
    )
    if locked.acknowledged_at is None:
        locked.acknowledged_at = timezone.now()
        locked.acknowledged_by = user
        locked.save(
            update_fields=["acknowledged_at", "acknowledged_by"]
        )
    return locked

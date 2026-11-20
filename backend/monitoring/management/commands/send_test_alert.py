from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from monitoring.models import AlertNotification, FloodPrediction
from monitoring.services.alert_service import (
    AlertServiceError,
    create_high_risk_alert,
    deliver_email_alert,
)


class Command(BaseCommand):
    help = (
        "Create clearly marked in-app and email test alerts from "
        "a genuine High-risk prediction."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--prediction-id",
            type=int,
            help=(
                "Genuine High-risk prediction to use. Defaults to "
                "the latest eligible prediction."
            ),
        )
        parser.add_argument(
            "--email-recipient",
            action="append",
            dest="email_recipients",
            help=(
                "Email recipient. Repeat for multiple recipients. "
                "Defaults to ALERT_EMAIL_RECIPIENTS."
            ),
        )

    def handle(self, *args, **options):
        predictions = FloodPrediction.objects.select_related(
            "observation__county"
        ).filter(
            risk_level=FloodPrediction.RiskLevel.HIGH,
            observation__is_synthetic=False,
        )

        prediction_id = options["prediction_id"]
        if prediction_id is not None:
            predictions = predictions.filter(pk=prediction_id)

        prediction = predictions.order_by(
            "-observation__observation_date",
            "observation__county_id",
        ).first()

        if prediction is None:
            raise CommandError(
                "No eligible genuine High-risk prediction was found."
            )

        recipients = (
            options["email_recipients"]
            or settings.ALERT_EMAIL_RECIPIENTS
        )
        if not recipients:
            raise CommandError(
                "Provide --email-recipient or configure "
                "ALERT_EMAIL_RECIPIENTS."
            )

        try:
            in_app = create_high_risk_alert(
                prediction,
                channel=AlertNotification.Channel.IN_APP,
                recipient=settings.IN_APP_ALERT_RECIPIENT,
                is_test=True,
            )
        except AlertServiceError as exc:
            raise CommandError(str(exc)) from exc

        emails_sent = 0
        emails_failed = 0

        for recipient in dict.fromkeys(recipients):
            try:
                email = create_high_risk_alert(
                    prediction,
                    channel=AlertNotification.Channel.EMAIL,
                    recipient=recipient,
                    is_test=True,
                )
            except AlertServiceError as exc:
                raise CommandError(str(exc)) from exc

            if not email.created:
                email.alert.status = AlertNotification.Status.PENDING
                email.alert.failure_reason = ""
                email.alert.sent_at = None
                email.alert.save(
                    update_fields=[
                        "status",
                        "failure_reason",
                        "sent_at",
                    ]
                )

            delivered = deliver_email_alert(email.alert)
            emails_sent += int(
                delivered.status == AlertNotification.Status.SENT
            )
            emails_failed += int(
                delivered.status == AlertNotification.Status.FAILED
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Test alert completed: "
                f"in-app {'created' if in_app.created else 'existing'}, "
                f"{emails_sent} emails sent, "
                f"{emails_failed} emails failed."
            )
        )

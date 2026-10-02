from django.core.management.base import BaseCommand, CommandError

from monitoring.models import AlertNotification
from monitoring.services.alert_service import (
    AlertServiceError,
    mark_alert_failed,
    mark_alert_sent,
)


class Command(BaseCommand):
    help = "Mark an alert as sent or failed."

    def add_arguments(self, parser):
        parser.add_argument("--alert-id", required=True, type=int)

        status = parser.add_mutually_exclusive_group(required=True)
        status.add_argument("--sent", action="store_true")
        status.add_argument("--failed", action="store_true")

        parser.add_argument("--failure-reason")

    def handle(self, *args, **options):
        try:
            alert = AlertNotification.objects.get(
                pk=options["alert_id"]
            )
        except AlertNotification.DoesNotExist as exc:
            raise CommandError("Alert not found.") from exc

        try:
            if options["sent"]:
                if options["failure_reason"]:
                    raise AlertServiceError(
                        "--failure-reason cannot be used with --sent."
                    )
                alert = mark_alert_sent(alert)
            else:
                alert = mark_alert_failed(
                    alert,
                    options["failure_reason"] or "",
                )
        except AlertServiceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Alert {alert.pk} updated to {alert.status}."
            )
        )
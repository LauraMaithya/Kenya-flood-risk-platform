from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import localdate

from monitoring.models import EnvironmentalObservation
from monitoring.services.live_alerts import (
    LiveAlertError,
    create_live_high_risk_alerts,
)


class Command(BaseCommand):
    help = "Create missing notifications for recent genuine live High predictions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Number of recent calendar days to reconcile. Default: 7.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1 or days > 90:
            raise CommandError("--days must be between 1 and 90.")
        end = localdate()
        start = end - timedelta(days=days - 1)
        dates = (
            EnvironmentalObservation.objects.filter(
                observation_date__range=(start, end),
                source=EnvironmentalObservation.Source.LIVE_API_IOT,
                is_synthetic=False,
                predictions__risk_level="High",
            )
            .order_by("observation_date")
            .values_list("observation_date", flat=True)
            .distinct()
        )
        totals = {
            "high": 0,
            "created": 0,
            "existing": 0,
            "sent": 0,
            "failed": 0,
        }
        try:
            for observation_date in dates:
                summary = create_live_high_risk_alerts(observation_date)
                totals["high"] += summary.high_risk_predictions
                totals["created"] += summary.alerts_created
                totals["existing"] += summary.alerts_existing
                totals["sent"] += summary.emails_sent
                totals["failed"] += summary.emails_failed
        except LiveAlertError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Live alert reconciliation complete: "
                f"{totals['high']} High predictions, "
                f"{totals['created']} alerts created, "
                f"{totals['existing']} already present, "
                f"{totals['sent']} emails sent, "
                f"{totals['failed']} emails failed."
            )
        )

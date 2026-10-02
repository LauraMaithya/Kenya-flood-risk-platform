from django.core.management.base import BaseCommand, CommandError

from monitoring.models import (
    AlertNotification,
    FloodPrediction,
)
from monitoring.services.alert_service import (
    AlertServiceError,
    create_high_risk_alert,
)


class Command(BaseCommand):
    help = "Create pending alerts for High-risk predictions."

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(
            required=True
        )
        selection.add_argument(
            "--prediction-id",
            type=int,
            help="Create an alert for one High-risk prediction.",
        )
        selection.add_argument(
            "--all",
            action="store_true",
            help="Create alerts for all eligible predictions.",
        )
        parser.add_argument(
            "--channel",
            required=True,
            choices=["IN_APP", "EMAIL"],
        )
        parser.add_argument("--recipient", required=True)
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        channel = options["channel"]
        recipient = options["recipient"]
        limit = options["limit"]

        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero.")

        prediction_id = options["prediction_id"]

        if prediction_id is not None:
            try:
                predictions = [
                    FloodPrediction.objects.select_related(
                        "observation__county"
                    ).get(
                        pk=prediction_id,
                        risk_level="High",
                    )
                ]
            except FloodPrediction.DoesNotExist as exc:
                raise CommandError(
                    "A High-risk prediction with that ID "
                    "was not found."
                ) from exc
        else:
            existing_prediction_ids = (
                AlertNotification.objects.filter(
                    channel=channel,
                    recipient=recipient,
                ).values_list("prediction_id", flat=True)
            )

            queryset = (
                FloodPrediction.objects.select_related(
                    "observation__county"
                )
                .filter(risk_level="High")
                .exclude(pk__in=existing_prediction_ids)
                .order_by(
                    "observation__observation_date",
                    "observation__county_id",
                )
            )

            if limit is not None:
                queryset = queryset[:limit]

            predictions = queryset.iterator()

        processed = 0
        created = 0
        existing = 0

        for prediction in predictions:
            try:
                result = create_high_risk_alert(
                    prediction,
                    channel=channel,
                    recipient=recipient,
                )
            except AlertServiceError as exc:
                raise CommandError(
                    f"Prediction {prediction.pk}: {exc}"
                ) from exc

            processed += 1
            created += int(result.created)
            existing += int(not result.created)

        self.stdout.write(
            self.style.SUCCESS(
                "Alert generation completed: "
                f"{processed} processed, "
                f"{created} created, "
                f"{existing} existing."
            )
        )
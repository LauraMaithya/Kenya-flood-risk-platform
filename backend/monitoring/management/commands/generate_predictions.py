from django.core.management.base import BaseCommand, CommandError

from monitoring.models import (
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.prediction_service import (
    get_model_release,
)
from monitoring.services.prediction_storage import (
    PredictionStorageError,
    store_prediction,
)


class Command(BaseCommand):
    help = "Generate and store flood-risk predictions."

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(
            required=True
        )
        selection.add_argument(
            "--observation-id",
            type=int,
            help="Generate a prediction for one observation.",
        )
        selection.add_argument(
            "--all",
            action="store_true",
            help="Predict all real observations without a result.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of observations to process.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero.")

        observation_id = options["observation_id"]

        if observation_id is not None:
            try:
                observations = [
                    EnvironmentalObservation.objects.get(
                        pk=observation_id,
                        is_synthetic=False,
                    )
                ]
            except EnvironmentalObservation.DoesNotExist as exc:
                raise CommandError(
                    "A real observation with that ID was not found."
                ) from exc
        else:
            release = get_model_release()

            existing_observation_ids = (
                FloodPrediction.objects.filter(
                    model_release_id=release.release_id
                ).values_list("observation_id", flat=True)
            )

            queryset = (
                EnvironmentalObservation.objects.filter(
                    is_synthetic=False
                )
                .exclude(pk__in=existing_observation_ids)
                .order_by("observation_date", "county_id")
            )

            if limit is not None:
                queryset = queryset[:limit]

            observations = queryset.iterator()

        processed = 0
        created = 0
        updated = 0

        for observation in observations:
            try:
                stored = store_prediction(observation)
            except PredictionStorageError as exc:
                raise CommandError(
                    f"Observation {observation.pk}: {exc}"
                ) from exc

            processed += 1
            created += int(stored.created)
            updated += int(not stored.created)

        self.stdout.write(
            self.style.SUCCESS(
                "Prediction generation completed: "
                f"{processed} processed, "
                f"{created} created, "
                f"{updated} updated."
            )
        )
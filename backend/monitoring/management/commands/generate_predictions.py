from itertools import islice

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
    store_prediction_batch,
)


DEFAULT_BATCH_SIZE = 1000


def _chunks(iterator, batch_size):
    while True:
        batch = list(islice(iterator, batch_size))

        if not batch:
            return

        yield batch


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
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=(
                "Number of observations processed in each "
                f"vectorized batch. Default: {DEFAULT_BATCH_SIZE}."
            ),
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        batch_size = options["batch_size"]

        if limit is not None and limit <= 0:
            raise CommandError(
                "--limit must be greater than zero."
            )

        if batch_size <= 0:
            raise CommandError(
                "--batch-size must be greater than zero."
            )

        observation_id = options["observation_id"]

        if observation_id is not None:
            self._predict_one(observation_id)
            return

        self._predict_all(
            limit=limit,
            batch_size=batch_size,
        )

    def _predict_one(self, observation_id):
        try:
            observation = (
                EnvironmentalObservation.objects.get(
                    pk=observation_id,
                    is_synthetic=False,
                )
            )
        except EnvironmentalObservation.DoesNotExist as exc:
            raise CommandError(
                "A real observation with that ID was not found."
            ) from exc

        try:
            stored = store_prediction(observation)
        except PredictionStorageError as exc:
            raise CommandError(
                f"Observation {observation.pk}: {exc}"
            ) from exc

        created = int(stored.created)
        updated = int(not stored.created)

        self.stdout.write(
            self.style.SUCCESS(
                "Prediction generation completed: "
                f"1 processed, "
                f"{created} created, "
                f"{updated} updated."
            )
        )

    def _predict_all(self, *, limit, batch_size):
        release = get_model_release()

        existing_observation_ids = (
            FloodPrediction.objects.filter(
                model_release_id=release.release_id
            ).values_list(
                "observation_id",
                flat=True,
            )
        )

        queryset = (
            EnvironmentalObservation.objects.filter(
                is_synthetic=False
            )
            .exclude(pk__in=existing_observation_ids)
            .order_by(
                "observation_date",
                "county_id",
            )
        )

        if limit is not None:
            queryset = queryset[:limit]

        observation_iterator = queryset.iterator(
            chunk_size=batch_size
        )

        processed = 0
        created = 0
        skipped_existing = 0
        batch_number = 0

        for observation_batch in _chunks(
            observation_iterator,
            batch_size,
        ):
            batch_number += 1

            try:
                result = store_prediction_batch(
                    observation_batch,
                    database_batch_size=batch_size,
                )
            except PredictionStorageError as exc:
                first_id = observation_batch[0].pk
                last_id = observation_batch[-1].pk

                raise CommandError(
                    "Prediction batch failed for observation "
                    f"IDs {first_id}–{last_id}: {exc}"
                ) from exc

            processed += result.processed
            created += result.created
            skipped_existing += result.skipped_existing

            self.stdout.write(
                "Batch "
                f"{batch_number}: "
                f"{result.processed} processed, "
                f"{result.created} created, "
                f"{result.skipped_existing} skipped."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Prediction generation completed: "
                f"{processed} processed, "
                f"{created} created, "
                f"{skipped_existing} skipped existing."
            )
        )
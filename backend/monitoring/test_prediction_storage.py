from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.prediction_service import PredictionResult
from monitoring.services.prediction_storage import (
    PredictionStorageError,
    store_prediction,
    store_prediction_batch,
)


RELEASE_ID = "kenya_flood_risk_rf_v1_0_0"

SINGLE_PREDICTION_PATCH = (
    "monitoring.services.prediction_storage."
    "predict_observation"
)

BATCH_PREDICTION_PATCH = (
    "monitoring.services.prediction_storage."
    "predict_observations"
)

STORAGE_RELEASE_PATCH = (
    "monitoring.services.prediction_storage."
    "get_model_release"
)

COMMAND_RELEASE_PATCH = (
    "monitoring.management.commands."
    "generate_predictions.get_model_release"
)


class PredictionStorageTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="047",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            has_nasa_power_coverage=True,
        )

        self.observation = self.create_observation(
            observation_date=date(2026, 1, 15),
            source_record_id="047:2026-01-15",
        )

        self.model_result = PredictionResult(
            risk_level="High",
            probability_low=0.10,
            probability_medium=0.20,
            probability_high=0.70,
            model_release_id=RELEASE_ID,
            model_version="1.0.0",
            high_threshold=0.44,
        )

        self.release = SimpleNamespace(
            release_id=RELEASE_ID,
        )

    def create_observation(
        self,
        *,
        observation_date,
        source_record_id,
        is_synthetic=False,
    ):
        return EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("42.5"),
            temperature_mean_c=Decimal("24.8"),
            relative_humidity_mean_pct=Decimal("71.2"),
            soil_wetness_mean_fraction=Decimal("0.48"),
            soil_wetness_max_fraction=Decimal("0.63"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
            source_record_id=source_record_id,
            is_synthetic=is_synthetic,
            quality_review_required=False,
        )

    @patch(SINGLE_PREDICTION_PATCH)
    def test_prediction_is_stored(self, predict_mock):
        predict_mock.return_value = self.model_result

        stored = store_prediction(self.observation)

        self.assertTrue(stored.created)
        self.assertEqual(
            FloodPrediction.objects.count(),
            1,
        )

        prediction = stored.prediction

        self.assertEqual(
            prediction.risk_level,
            "High",
        )
        self.assertEqual(
            prediction.model_release_id,
            RELEASE_ID,
        )
        self.assertEqual(
            prediction.decision_rule,
            "HIGH_THRESHOLD_0.44",
        )
        self.assertEqual(
            float(prediction.probability_high),
            0.70,
        )
        self.assertEqual(
            float(
                prediction.high_probability_threshold
            ),
            0.44,
        )

    @patch(SINGLE_PREDICTION_PATCH)
    def test_repeated_storage_is_idempotent(
        self,
        predict_mock,
    ):
        predict_mock.return_value = self.model_result

        first = store_prediction(self.observation)
        second = store_prediction(self.observation)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(
            FloodPrediction.objects.count(),
            1,
        )

    def test_unsaved_observation_is_rejected(self):
        observation = EnvironmentalObservation(
            is_synthetic=False
        )

        with self.assertRaisesRegex(
            PredictionStorageError,
            "must be saved",
        ):
            store_prediction(observation)

    def test_synthetic_observation_is_rejected(self):
        self.observation.is_synthetic = True
        self.observation.save(
            update_fields=["is_synthetic"]
        )

        with self.assertRaisesRegex(
            PredictionStorageError,
            "Synthetic observations",
        ):
            store_prediction(self.observation)

    @patch(SINGLE_PREDICTION_PATCH)
    def test_command_predicts_one_observation(
        self,
        predict_mock,
    ):
        predict_mock.return_value = self.model_result
        output = StringIO()

        call_command(
            "generate_predictions",
            "--observation-id",
            str(self.observation.pk),
            stdout=output,
        )

        self.assertIn(
            "1 processed",
            output.getvalue(),
        )
        self.assertIn(
            "1 created",
            output.getvalue(),
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            1,
        )

    @patch(BATCH_PREDICTION_PATCH)
    @patch(STORAGE_RELEASE_PATCH)
    def test_batch_storage_creates_predictions(
        self,
        release_mock,
        predict_mock,
    ):
        second_observation = self.create_observation(
            observation_date=date(2026, 1, 16),
            source_record_id="047:2026-01-16",
        )

        release_mock.return_value = self.release
        predict_mock.return_value = (
            self.model_result,
            self.model_result,
        )

        result = store_prediction_batch(
            [
                self.observation,
                second_observation,
            ]
        )

        self.assertEqual(result.processed, 2)
        self.assertEqual(result.created, 2)
        self.assertEqual(result.skipped_existing, 0)
        self.assertEqual(
            FloodPrediction.objects.count(),
            2,
        )

        predict_mock.assert_called_once()

        predicted_observations = (
            predict_mock.call_args.args[0]
        )

        self.assertEqual(
            list(predicted_observations),
            [
                self.observation,
                second_observation,
            ],
        )

    @patch(BATCH_PREDICTION_PATCH)
    @patch(STORAGE_RELEASE_PATCH)
    @patch(SINGLE_PREDICTION_PATCH)
    def test_batch_storage_skips_existing_prediction(
        self,
        single_predict_mock,
        release_mock,
        batch_predict_mock,
    ):
        single_predict_mock.return_value = (
            self.model_result
        )
        store_prediction(self.observation)

        second_observation = self.create_observation(
            observation_date=date(2026, 1, 16),
            source_record_id="047:2026-01-16",
        )

        release_mock.return_value = self.release
        batch_predict_mock.return_value = (
            self.model_result,
        )

        result = store_prediction_batch(
            [
                self.observation,
                second_observation,
            ]
        )

        self.assertEqual(result.processed, 2)
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped_existing, 1)
        self.assertEqual(
            FloodPrediction.objects.count(),
            2,
        )

        predicted_observations = (
            batch_predict_mock.call_args.args[0]
        )

        self.assertEqual(
            list(predicted_observations),
            [second_observation],
        )

    @patch(BATCH_PREDICTION_PATCH)
    @patch(STORAGE_RELEASE_PATCH)
    def test_batch_storage_rejects_synthetic_observation(
        self,
        release_mock,
        predict_mock,
    ):
        synthetic_observation = self.create_observation(
            observation_date=date(2026, 1, 16),
            source_record_id="047:2026-01-16",
            is_synthetic=True,
        )

        release_mock.return_value = self.release

        with self.assertRaisesRegex(
            PredictionStorageError,
            "Synthetic observations",
        ):
            store_prediction_batch(
                [
                    self.observation,
                    synthetic_observation,
                ]
            )

        predict_mock.assert_not_called()
        self.assertEqual(
            FloodPrediction.objects.count(),
            0,
        )

    @patch(BATCH_PREDICTION_PATCH)
    @patch(STORAGE_RELEASE_PATCH)
    @patch(COMMAND_RELEASE_PATCH)
    def test_all_mode_uses_batches_and_skips_existing(
        self,
        command_release_mock,
        storage_release_mock,
        predict_mock,
    ):
        second_observation = self.create_observation(
            observation_date=date(2026, 1, 16),
            source_record_id="047:2026-01-16",
        )

        command_release_mock.return_value = self.release
        storage_release_mock.return_value = self.release
        predict_mock.return_value = (
            self.model_result,
            self.model_result,
        )

        output = StringIO()

        call_command(
            "generate_predictions",
            "--all",
            "--batch-size",
            "2",
            stdout=output,
        )

        command_output = output.getvalue()

        self.assertIn(
            "Batch 1: 2 processed",
            command_output,
        )
        self.assertIn(
            "2 created",
            command_output,
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            2,
        )
        self.assertTrue(
            FloodPrediction.objects.filter(
                observation=second_observation,
                model_release_id=RELEASE_ID,
            ).exists()
        )

        second_output = StringIO()

        call_command(
            "generate_predictions",
            "--all",
            "--batch-size",
            "2",
            stdout=second_output,
        )

        self.assertIn(
            "0 processed",
            second_output.getvalue(),
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            2,
        )

    def test_command_rejects_invalid_batch_size(self):
        with self.assertRaisesRegex(
            Exception,
            "--batch-size must be greater than zero",
        ):
            call_command(
                "generate_predictions",
                "--all",
                "--batch-size",
                "0",
            )
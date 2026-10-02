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
)


PREDICTION_PATCH = (
    "monitoring.services.prediction_storage."
    "predict_observation"
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

        self.observation = EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=date(2026, 1, 15),
            precipitation_max_mm=Decimal("42.5"),
            temperature_mean_c=Decimal("24.8"),
            relative_humidity_mean_pct=Decimal("71.2"),
            soil_wetness_mean_fraction=Decimal("0.48"),
            soil_wetness_max_fraction=Decimal("0.63"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
            source_record_id="047:2026-01-15",
            is_synthetic=False,
            quality_review_required=False,
        )

        self.model_result = PredictionResult(
            risk_level="High",
            probability_low=0.10,
            probability_medium=0.20,
            probability_high=0.70,
            model_release_id="kenya_flood_risk_rf_v1_0_0",
            model_version="1.0.0",
            high_threshold=0.44,
        )

    @patch(PREDICTION_PATCH)
    def test_prediction_is_stored(self, predict_mock):
        predict_mock.return_value = self.model_result

        stored = store_prediction(self.observation)

        self.assertTrue(stored.created)
        self.assertEqual(FloodPrediction.objects.count(), 1)

        prediction = stored.prediction
        self.assertEqual(prediction.risk_level, "High")
        self.assertEqual(
            prediction.model_release_id,
            "kenya_flood_risk_rf_v1_0_0",
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
            float(prediction.high_probability_threshold),
            0.44,
        )

    @patch(PREDICTION_PATCH)
    def test_repeated_storage_is_idempotent(self, predict_mock):
        predict_mock.return_value = self.model_result

        first = store_prediction(self.observation)
        second = store_prediction(self.observation)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(FloodPrediction.objects.count(), 1)

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
        self.observation.save(update_fields=["is_synthetic"])

        with self.assertRaisesRegex(
            PredictionStorageError,
            "Synthetic observations",
        ):
            store_prediction(self.observation)

    @patch(PREDICTION_PATCH)
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

        self.assertIn("1 processed", output.getvalue())
        self.assertIn("1 created", output.getvalue())
        self.assertEqual(FloodPrediction.objects.count(), 1)

    @patch(PREDICTION_PATCH)
    def test_all_mode_skips_existing_prediction(
        self,
        predict_mock,
    ):
        predict_mock.return_value = self.model_result
        store_prediction(self.observation)

        second_observation = (
            EnvironmentalObservation.objects.create(
                county=self.county,
                observation_date=date(2026, 1, 16),
                precipitation_max_mm=Decimal("12.5"),
                temperature_mean_c=Decimal("25.1"),
                relative_humidity_mean_pct=Decimal("68.0"),
                soil_wetness_mean_fraction=Decimal("0.40"),
                soil_wetness_max_fraction=Decimal("0.55"),
                month_sin=Decimal("0.50000000"),
                month_cos=Decimal("0.86602540"),
                source_record_id="047:2026-01-16",
                is_synthetic=False,
                quality_review_required=False,
            )
        )

        output = StringIO()

        with patch(
            "monitoring.management.commands."
            "generate_predictions.get_model_release",
            return_value=SimpleNamespace(
                release_id="kenya_flood_risk_rf_v1_0_0"
            ),
        ):
            call_command(
                "generate_predictions",
                "--all",
                stdout=output,
            )

        self.assertIn("1 processed", output.getvalue())
        self.assertEqual(FloodPrediction.objects.count(), 2)
        self.assertTrue(
            FloodPrediction.objects.filter(
                observation=second_observation
            ).exists()
        )
        
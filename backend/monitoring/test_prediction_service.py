import csv
import unittest
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

from monitoring.services.prediction_service import (
    PredictionServiceError,
    get_model_release,
    predict_features,
    predict_observation,
)


MODEL_DIRECTORY = settings.MODEL_BUNDLE_PATH.parent
VERIFICATION_INPUT_PATH = (
    MODEL_DIRECTORY / "verification_input.csv"
)
VERIFICATION_OUTPUT_PATH = (
    MODEL_DIRECTORY / "verification_output.csv"
)


@unittest.skipUnless(
    settings.MODEL_BUNDLE_PATH.is_file(),
    "The local serialized model bundle is not available.",
)
class PredictionServiceTests(SimpleTestCase):
    def read_verification_rows(self):
        with VERIFICATION_INPUT_PATH.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as input_file:
            input_rows = list(csv.DictReader(input_file))

        with VERIFICATION_OUTPUT_PATH.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as output_file:
            output_rows = list(csv.DictReader(output_file))

        return input_rows, output_rows

    def test_release_matches_locked_contract(self):
        release = get_model_release()

        self.assertEqual(
            release.release_id,
            "kenya_flood_risk_rf_v1_0_0",
        )
        self.assertEqual(release.version, "1.0.0")
        self.assertEqual(release.high_threshold, 0.44)
        self.assertEqual(
            release.feature_names,
            (
                "precipitation_max_mm",
                "temperature_mean_c",
                "relative_humidity_mean_pct",
                "soil_wetness_mean_fraction",
                "soil_wetness_max_fraction",
                "month_sin",
                "month_cos",
            ),
        )
        self.assertEqual(
            release.model_class_order,
            ("High", "Low", "Medium"),
        )
        self.assertEqual(
            release.checksum,
            (
                "6463afdf5977e1dfadea92534d4471ba"
                "4d5f1d2dec038a757de7a39d81f9f444"
            ),
        )

    def test_saved_verification_predictions_are_reproduced(self):
        input_rows, expected_rows = (
            self.read_verification_rows()
        )

        self.assertEqual(len(input_rows), len(expected_rows))
        self.assertGreater(len(input_rows), 0)

        for row_number, (features, expected) in enumerate(
            zip(input_rows, expected_rows, strict=True),
            start=1,
        ):
            with self.subTest(row=row_number):
                result = predict_features(features)

                self.assertEqual(
                    result.risk_level,
                    expected["predicted_flood_risk_label"],
                )
                self.assertAlmostEqual(
                    result.probability_low,
                    float(expected["probability_low"]),
                    delta=1e-12,
                )
                self.assertAlmostEqual(
                    result.probability_medium,
                    float(expected["probability_medium"]),
                    delta=1e-12,
                )
                self.assertAlmostEqual(
                    result.probability_high,
                    float(expected["probability_high"]),
                    delta=1e-12,
                )

    def test_missing_feature_is_rejected(self):
        input_rows, _ = self.read_verification_rows()
        features = input_rows[0].copy()
        features.pop("month_cos")

        with self.assertRaisesRegex(
            PredictionServiceError,
            "Missing prediction features",
        ):
            predict_features(features)

    def test_nonfinite_feature_is_rejected(self):
        input_rows, _ = self.read_verification_rows()
        features = input_rows[0].copy()
        features["precipitation_max_mm"] = "nan"

        with self.assertRaisesRegex(
            PredictionServiceError,
            "must be finite",
        ):
            predict_features(features)

    def test_synthetic_observation_is_rejected(self):
        observation = SimpleNamespace(is_synthetic=True)

        with self.assertRaisesRegex(
            PredictionServiceError,
            "Synthetic observations",
        ):
            predict_observation(observation)
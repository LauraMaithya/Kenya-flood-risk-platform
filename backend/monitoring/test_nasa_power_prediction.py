from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
)
from monitoring.services.nasa_power_prediction import (
    NasaPowerPredictionError,
    predict_missing_nasa_power,
)
from monitoring.services.prediction_storage import (
    BatchStorageResult,
)


RELEASE_ID = "kenya_flood_risk_rf_v1_0_0"

RELEASE_PATCH = (
    "monitoring.services.nasa_power_prediction."
    "get_model_release"
)

STORAGE_PATCH = (
    "monitoring.services.nasa_power_prediction."
    "store_prediction_batch"
)


class NasaPowerPredictionTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.other_county = County.objects.create(
            code="040",
            name="Busia",
            slug="busia",
            latitude=Decimal("0.389952"),
            longitude=Decimal("34.193812"),
            has_nasa_power_coverage=True,
        )

    def create_observation(
        self,
        *,
        county,
        observation_date,
        source,
        source_record_id,
        is_synthetic=False,
    ):
        return EnvironmentalObservation.objects.create(
            county=county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("12.500"),
            temperature_mean_c=Decimal("23.50"),
            relative_humidity_mean_pct=Decimal("71.200"),
            soil_wetness_mean_fraction=Decimal("0.480000"),
            soil_wetness_max_fraction=Decimal("0.630000"),
            month_sin=Decimal("0.00000000"),
            month_cos=Decimal("1.00000000"),
            source=source,
            source_record_id=source_record_id,
            is_synthetic=is_synthetic,
            quality_review_required=False,
        )

    @patch(STORAGE_PATCH)
    @patch(RELEASE_PATCH)
    def test_only_matching_real_nasa_observations_are_predicted(
        self,
        release_mock,
        storage_mock,
    ):
        selected = self.create_observation(
            county=self.county,
            observation_date=date(2026, 1, 1),
            source=(
                EnvironmentalObservation.Source.NASA_POWER
            ),
            source_record_id="NASA_POWER:030:2026-01-01",
        )
        self.create_observation(
            county=self.other_county,
            observation_date=date(2026, 1, 1),
            source=(
                EnvironmentalObservation.Source.NASA_POWER
            ),
            source_record_id="NASA_POWER:040:2026-01-01",
        )
        self.create_observation(
            county=self.county,
            observation_date=date(2026, 1, 2),
            source=(
                EnvironmentalObservation.Source.SIMULATED_IOT
            ),
            source_record_id="SIMULATED_IOT:030:2026-01-02",
            is_synthetic=True,
        )

        release_mock.return_value = SimpleNamespace(
            release_id=RELEASE_ID,
        )
        storage_mock.return_value = BatchStorageResult(
            processed=1,
            created=1,
            skipped_existing=0,
        )

        summary = predict_missing_nasa_power(
            [self.county],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            batch_size=10,
        )

        self.assertEqual(summary.observations_found, 1)
        self.assertEqual(summary.predictions_pending, 1)
        self.assertEqual(summary.predictions_created, 1)
        self.assertEqual(summary.predictions_existing, 0)
        self.assertEqual(summary.batches_processed, 1)

        predicted_batch = list(
            storage_mock.call_args.args[0]
        )

        self.assertEqual(predicted_batch, [selected])

    @patch(STORAGE_PATCH)
    @patch(RELEASE_PATCH)
    def test_empty_period_creates_no_predictions(
        self,
        release_mock,
        storage_mock,
    ):
        release_mock.return_value = SimpleNamespace(
            release_id=RELEASE_ID,
        )

        summary = predict_missing_nasa_power(
            [self.county],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
        )

        self.assertEqual(summary.observations_found, 0)
        self.assertEqual(summary.predictions_pending, 0)
        self.assertEqual(summary.predictions_created, 0)
        self.assertEqual(summary.batches_processed, 0)
        storage_mock.assert_not_called()

    def test_empty_county_collection_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerPredictionError,
            "At least one county",
        ):
            predict_missing_nasa_power(
                [],
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
            )

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerPredictionError,
            "start date",
        ):
            predict_missing_nasa_power(
                [self.county],
                start_date=date(2026, 1, 2),
                end_date=date(2026, 1, 1),
            )

    def test_invalid_batch_size_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerPredictionError,
            "batch size",
        ):
            predict_missing_nasa_power(
                [self.county],
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
                batch_size=0,
            )
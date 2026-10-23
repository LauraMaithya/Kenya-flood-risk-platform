from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
)
from monitoring.services.open_meteo import (
    OpenMeteoDailyPoint,
)
from monitoring.services.open_meteo_refresh import (
    refresh_open_meteo_county,
)
from monitoring.services.open_meteo_storage import (
    OpenMeteoStorageSummary,
)


FETCH_PATCH = (
    "monitoring.services.open_meteo_refresh."
    "fetch_open_meteo_daily_point"
)

STORAGE_PATCH = (
    "monitoring.services.open_meteo_refresh."
    "store_open_meteo_daily_point"
)

PREDICTION_PATCH = (
    "monitoring.services.open_meteo_refresh."
    "store_prediction"
)


class OpenMeteoRefreshTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.observation_date = date(2026, 10, 23)
        self.point = OpenMeteoDailyPoint(
            observation_date=self.observation_date,
            precipitation_mm=Decimal("0.000"),
            temperature_c=Decimal("28.56"),
            relative_humidity_pct=Decimal("40.875"),
            soil_wetness_mean_fraction=Decimal(
                "0.055875"
            ),
            soil_wetness_max_fraction=Decimal(
                "0.057000"
            ),
        )

    def create_live_observation(self):
        return EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=self.observation_date,
            precipitation_max_mm=Decimal("0.000"),
            temperature_mean_c=Decimal("28.56"),
            relative_humidity_mean_pct=Decimal(
                "40.875"
            ),
            soil_wetness_mean_fraction=Decimal(
                "0.055875"
            ),
            soil_wetness_max_fraction=Decimal(
                "0.057000"
            ),
            month_sin=Decimal("-1.00000000"),
            month_cos=Decimal("0.00000000"),
            source=(
                EnvironmentalObservation.Source.LIVE_API_IOT
            ),
            source_record_id=(
                "OPEN_METEO_030_20261023"
            ),
            is_synthetic=False,
            quality_review_required=True,
        )

    @patch(PREDICTION_PATCH)
    @patch(STORAGE_PATCH)
    @patch(FETCH_PATCH)
    def test_refresh_extracts_stores_and_predicts(
        self,
        fetch_mock,
        storage_mock,
        prediction_mock,
    ):
        fetch_mock.return_value = self.point

        def storage_result(*args, **kwargs):
            self.create_live_observation()

            return OpenMeteoStorageSummary(
                device_created=True,
                reading_created=True,
                reading_updated=False,
                observation_created=True,
                observation_updated=False,
                observation_preserved=False,
                dry_run=False,
            )

        storage_mock.side_effect = storage_result
        prediction_mock.return_value = (
            SimpleNamespace(created=True)
        )

        summary = refresh_open_meteo_county(
            self.county,
            observation_date=self.observation_date,
            timeout=45,
        )

        self.assertTrue(summary.observation_created)
        self.assertTrue(summary.prediction_created)
        self.assertFalse(summary.prediction_existing)
        fetch_mock.assert_called_once()
        prediction_mock.assert_called_once()

    @patch(PREDICTION_PATCH)
    @patch(STORAGE_PATCH)
    @patch(FETCH_PATCH)
    def test_dry_run_does_not_predict(
        self,
        fetch_mock,
        storage_mock,
        prediction_mock,
    ):
        fetch_mock.return_value = self.point
        storage_mock.return_value = (
            OpenMeteoStorageSummary(
                device_created=True,
                reading_created=True,
                reading_updated=False,
                observation_created=True,
                observation_updated=False,
                observation_preserved=False,
                dry_run=True,
            )
        )

        summary = refresh_open_meteo_county(
            self.county,
            observation_date=self.observation_date,
            dry_run=True,
        )

        self.assertTrue(summary.dry_run)
        prediction_mock.assert_not_called()

    def test_county_without_coordinates_is_rejected(self):
        self.county.latitude = None
        self.county.longitude = None
        self.county.save(
            update_fields=[
                "latitude",
                "longitude",
            ]
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "does not have coordinates",
        ):
            refresh_open_meteo_county(
                self.county,
                observation_date=self.observation_date,
            )
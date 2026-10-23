from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from monitoring.models import (
    County,
    EnvironmentalObservation,
    SensorDevice,
    SensorReading,
)
from monitoring.services.open_meteo import (
    OpenMeteoDailyPoint,
)
from monitoring.services.open_meteo_storage import (
    store_open_meteo_daily_point,
)


class OpenMeteoStorageTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.point = OpenMeteoDailyPoint(
            observation_date=date(2026, 10, 23),
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

    def test_point_creates_device_reading_and_observation(self):
        summary = store_open_meteo_daily_point(
            self.county,
            self.point,
            retrieved_at=timezone.now(),
        )

        self.assertTrue(summary.device_created)
        self.assertTrue(summary.reading_created)
        self.assertTrue(summary.observation_created)

        device = SensorDevice.objects.get()
        reading = SensorReading.objects.get()
        observation = (
            EnvironmentalObservation.objects.get()
        )

        self.assertEqual(
            device.data_origin,
            SensorDevice.DataOrigin.LIVE_API_ASSISTED,
        )
        self.assertFalse(device.is_simulated)
        self.assertFalse(reading.is_simulated)
        self.assertIsNone(reading.water_level_m)
        self.assertEqual(
            reading.upstream_provider,
            SensorReading.UpstreamProvider.OPEN_METEO,
        )
        self.assertEqual(
            observation.source,
            EnvironmentalObservation.Source.LIVE_API_IOT,
        )
        self.assertFalse(observation.is_synthetic)
        self.assertTrue(
            observation.quality_review_required
        )

    def test_repeated_storage_is_idempotent(self):
        retrieved_at = timezone.now()

        store_open_meteo_daily_point(
            self.county,
            self.point,
            retrieved_at=retrieved_at,
        )
        second = store_open_meteo_daily_point(
            self.county,
            self.point,
            retrieved_at=retrieved_at,
        )

        self.assertFalse(second.device_created)
        self.assertFalse(second.reading_created)
        self.assertFalse(second.reading_updated)
        self.assertFalse(second.observation_created)
        self.assertFalse(second.observation_updated)
        self.assertEqual(
            SensorDevice.objects.count(),
            1,
        )
        self.assertEqual(
            SensorReading.objects.count(),
            1,
        )
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            1,
        )

    def test_existing_nasa_observation_is_preserved(self):
        EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=(
                self.point.observation_date
            ),
            precipitation_max_mm=Decimal("1.000"),
            temperature_mean_c=Decimal("25.00"),
            relative_humidity_mean_pct=Decimal(
                "70.000"
            ),
            soil_wetness_mean_fraction=Decimal(
                "0.400000"
            ),
            soil_wetness_max_fraction=Decimal(
                "0.500000"
            ),
            month_sin=Decimal("-1.00000000"),
            month_cos=Decimal("0.00000000"),
            source=(
                EnvironmentalObservation.Source.NASA_POWER
            ),
            source_record_id=(
                "NASA_POWER_030_20261023"
            ),
            is_synthetic=False,
        )

        summary = store_open_meteo_daily_point(
            self.county,
            self.point,
        )
        observation = (
            EnvironmentalObservation.objects.get()
        )

        self.assertTrue(
            summary.observation_preserved
        )
        self.assertEqual(
            observation.source,
            EnvironmentalObservation.Source.NASA_POWER,
        )
        self.assertEqual(
            observation.precipitation_max_mm,
            Decimal("1.000"),
        )

    def test_dry_run_rolls_back_all_records(self):
        summary = store_open_meteo_daily_point(
            self.county,
            self.point,
            dry_run=True,
        )

        self.assertTrue(summary.dry_run)
        self.assertEqual(
            SensorDevice.objects.count(),
            0,
        )
        self.assertEqual(
            SensorReading.objects.count(),
            0,
        )
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )